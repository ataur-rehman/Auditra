"""Administration: users, employees and accounts, catalogue, rules, agents, audit trail, reset."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from ..incidents import ORG_LEVEL_CODES
from ..models import (
    Agent, AiDayScore, AuditEntry, AuditraUser, BreachRecord, CatalogueEntry, ComplianceJobRun, Employee,
    EmployeeAccount, EnrolmentCode, Event, Incident, NotificationLog, Rule, normalize_account,
)
from ..permissions import IsAdminOrComplianceOfficer, IsAdminUser
from ..serializers import (
    AgentSerializer, AuditEntrySerializer, CatalogueEntrySerializer, EmployeeAccountSerializer, EmployeeSerializer,
    RuleSerializer, UserSerializer,
)
from .common import AuditedModelMixin, Pages, audit


class UserViewSet(AuditedModelMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    audit_label = 'user'
    serializer_class = UserSerializer
    queryset = AuditraUser.objects.order_by('username')

    def perform_destroy(self, instance):
        if instance == self.request.user:
            from rest_framework.exceptions import ValidationError
            raise ValidationError('You cannot delete your own account.')
        super().perform_destroy(instance)


class EmployeeViewSet(AuditedModelMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    audit_label = 'employee'
    serializer_class = EmployeeSerializer
    queryset = Employee.objects.select_related('login').prefetch_related('accounts', 'agents')

    def perform_update(self, serializer):
        super().perform_update(serializer)
        _refresh_shift_flags(serializer.instance)

    @action(detail=True, methods=['post'], url_path='accounts')
    def add_account(self, request, pk=None):
        employee = self.get_object()
        account = normalize_account(request.data.get('account'))
        if not account:
            return Response({'error': 'account is required, e.g. MACBOOK\\bilal'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            link, result = link_account(account, employee)
        except AccountTaken as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        audit(request, 'employee.account_link', account, employee=employee.full_name, **result)
        return Response({**EmployeeAccountSerializer(link).data, **result}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='login')
    def create_login(self, request, pk=None):
        """Create (or reset the password of) the employee's own console login. The password is shown once."""
        employee = self.get_object()
        password = secrets.token_urlsafe(9)
        user = AuditraUser.objects.filter(employee=employee).first()
        created = user is None
        if created:
            username = str(request.data.get('username') or employee.employee_code or '').strip().lower()
            if not username:
                return Response({'error': 'username is required.'}, status=status.HTTP_400_BAD_REQUEST)
            if AuditraUser.objects.filter(username__iexact=username).exists():
                return Response({'error': f'The username {username} is already taken.'},
                                status=status.HTTP_400_BAD_REQUEST)
            first, _, last = employee.full_name.partition(' ')
            user = AuditraUser(username=username, role='employee', employee=employee, email=employee.email,
                               first_name=first[:150], last_name=last[:150])
        user.set_password(password)
        user.is_active = True
        user.save()
        audit(request, 'employee.login_create' if created else 'employee.login_reset', user.username,
              employee=employee.full_name)
        return Response({'username': user.username, 'password': password, 'created': created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='enrolment-code')
    def enrolment_code(self, request, pk=None):
        """An admin issues a one-time code for an employee's laptop (for employees without a console login)."""
        employee = self.get_object()
        record, code = EnrolmentCode.issue(employee, request.user, settings.ENROLMENT_CODE_MINUTES)
        audit(request, 'employee.enrolment_code', employee.full_name, expires_at=record.expires_at.isoformat())
        return Response({'code': code, 'expires_at': record.expires_at}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'accounts/(?P<account_id>[^/.]+)')
    def remove_account(self, request, pk=None, account_id=None):
        employee = self.get_object()
        link = EmployeeAccount.objects.filter(pk=account_id, employee=employee).first()
        if not link:
            return Response(status=status.HTTP_404_NOT_FOUND)
        account = link.account
        link.delete()
        result = _reassign(account, None)
        audit(request, 'employee.account_unlink', account, employee=employee.full_name, **result)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountTaken(ValueError):
    pass


def link_account(account, employee):
    """Link a Windows account to an employee and move its recent activity to them. Raises AccountTaken."""
    account = normalize_account(account)
    existing = EmployeeAccount.objects.filter(account=account).select_related('employee').first()
    if existing and existing.employee_id != employee.id:
        raise AccountTaken(f'{account} already belongs to {existing.employee.full_name}.')
    link, _ = EmployeeAccount.objects.get_or_create(account=account, defaults={'employee': employee})
    return link, _reassign(account, employee)


def _account_events(account):
    if '\\' in account:
        return Event.objects.filter(account__iexact=account)
    return Event.objects.filter(account__iendswith='\\' + account)


def _reassign(account, employee):
    """Move an account's recent activity to (or away from) an employee and re-run detection on it.

    Permissions, shift and role decide what is a violation, so incidents raised under the old owner are
    re-evaluated: untouched open ones are replaced, ones an officer already acted on are kept.
    """
    from ..ingest import analyse_events

    since = timezone.now() - timedelta(days=7)
    events = list(_account_events(account).filter(occurred_at__gte=since).order_by('occurred_at'))
    for event in events:
        event.employee = employee
        if employee:
            event.outside_shift = not employee.is_on_shift(event.occurred_at)
        else:
            local = timezone.localtime(event.occurred_at)
            event.outside_shift = local.weekday() >= 5 or not (8 <= local.hour < 18)
    Event.objects.bulk_update(events, ['employee', 'outside_shift'])
    _account_events(account).filter(occurred_at__lt=since).update(employee=employee)

    stale = (
        Incident.objects.filter(account__iexact=account, status='OPEN', actions__isnull=True)
        .exclude(rule__code__in=ORG_LEVEL_CODES)
    )
    replaced = stale.count()
    stale.delete()
    kept = Incident.objects.filter(account__iexact=account)
    kept.update(employee=employee)
    created = analyse_events(events)['incidents_created'] if events else 0
    return {'events_relinked': len(events), 'incidents_replaced': replaced, 'incidents_raised': created}


def _refresh_shift_flags(employee):
    for event in Event.objects.filter(employee=employee).only('id', 'occurred_at', 'outside_shift'):
        outside = not employee.is_on_shift(event.occurred_at)
        if outside != event.outside_shift:
            Event.objects.filter(pk=event.pk).update(outside_shift=outside)


class CatalogueViewSet(AuditedModelMixin, viewsets.ModelViewSet):
    audit_label = 'catalogue'
    serializer_class = CatalogueEntrySerializer
    queryset = CatalogueEntry.objects.select_related('processing_activity')

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAdminOrComplianceOfficer()]
        return [IsAdminUser()]


class RuleViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = RuleSerializer
    queryset = Rule.objects.annotate(incident_count=Count('incidents')).order_by('source', 'code')

    def get_permissions(self):
        if self.action == 'list':
            return [IsAdminOrComplianceOfficer()]
        return [IsAdminUser()]

    def perform_update(self, serializer):
        rule = serializer.save()
        audit(self.request, 'rule.enable' if rule.enabled else 'rule.disable', rule.code)


class AgentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = AgentSerializer
    queryset = Agent.objects.annotate(event_count=Count('events')).order_by('hostname')

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        agent = self.get_object()
        agent.revoked = not agent.revoked
        agent.save(update_fields=['revoked'])
        audit(request, 'agent.revoke' if agent.revoked else 'agent.restore', agent.hostname)
        return Response(AgentSerializer(agent).data)


class AuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = AuditEntrySerializer
    pagination_class = Pages
    queryset = AuditEntry.objects.select_related('actor')


@api_view(['GET'])
@permission_classes([IsAdminUser])
def unlinked_accounts(request):
    rows = (
        Event.objects.filter(employee__isnull=True)
        .exclude(event_type__in=['AUTOMATED_DECISION', 'RETENTION_EXCEEDED'])
        .values('account', 'machine')
        .annotate(events=Count('id'), last_seen=Max('occurred_at'))
        .order_by('-last_seen')
    )
    return Response(list(rows[:100]))


@api_view(['GET'])
@permission_classes([IsAdminUser])
def health(request):
    jobs = ComplianceJobRun.objects.order_by('-started_at')[:10]
    return Response({
        'agents': AgentSerializer(Agent.objects.annotate(event_count=Count('events')), many=True).data,
        'jobs': [{'started_at': j.started_at, 'status': j.status, 'incidents_created': j.incidents_created,
                  'error': j.error_message} for j in jobs],
        'counts': {
            'events': Event.objects.count(),
            'incidents': Incident.objects.count(),
            'employees': Employee.objects.count(),
            'catalogue': CatalogueEntry.objects.count(),
            'rules_enabled': Rule.objects.filter(enabled=True).count(),
            'rules_total': Rule.objects.count(),
        },
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
def reset_monitoring(request):
    """Deletes recorded activity (events, incidents, AI scores, breaches opened from incidents). Configuration
    and GDPR records stay."""
    if request.data.get('confirm') != 'RESET':
        return Response({'error': 'Send {"confirm": "RESET"} to delete all recorded activity.'},
                        status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        counts = {
            'breaches': BreachRecord.objects.filter(incident__isnull=False).delete()[0],
            'incidents': Incident.objects.all().delete()[0],
            'events': Event.objects.all().delete()[0],
            'ai_scores': AiDayScore.objects.all().delete()[0],
            'notifications': NotificationLog.objects.all().delete()[0],
        }
    audit(request, 'monitoring.reset', 'all activity', **counts)
    return Response(counts)
