"""Console endpoints for compliance officers (admins can use them too)."""
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from ..ai import day_bounds
from ..models import (
    Agent, AiDayScore, AutomatedDecision, BreachRecord, ConsentRecord, DataSubject, DataSubjectRequest,
    DPORecord, Employee, Event, Incident, IncidentAction, ProcessingActivity,
)
from ..permissions import IsAdminOrComplianceOfficer
from ..serializers import (
    AgentSerializer, AutomatedDecisionSerializer, BreachRecordSerializer, ConsentRecordSerializer,
    DataSubjectRequestSerializer, DataSubjectSerializer, DPORecordSerializer, EmployeeSerializer, EventSerializer,
    IncidentDetailSerializer, IncidentListSerializer, ProcessingActivitySerializer,
)
from .common import AuditedModelMixin, Pages, audit

LIVE_OVERLAP = timedelta(seconds=5)

ACTION_STATUS = {
    'ACKNOWLEDGE': 'ACKNOWLEDGED',
    'INVESTIGATE': 'INVESTIGATING',
    'ESCALATE': 'ESCALATED',
    'RESOLVE': 'RESOLVED',
    'FALSE_POSITIVE': 'FALSE_POSITIVE',
    'REOPEN': 'OPEN',
    'NOTE': None,
}


def _since(request, name='since'):
    raw = request.query_params.get(name)
    if not raw:
        return None
    value = parse_datetime(raw.replace(' ', '+'))
    if value and timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def kpis():
    now = timezone.now()
    start, _ = day_bounds(timezone.localdate())
    open_qs = Incident.objects.exclude(status__in=Incident.CLOSED_STATUSES)
    closed = Incident.objects.filter(status__in=Incident.CLOSED_STATUSES)
    false_pos = closed.filter(status='FALSE_POSITIVE').count()
    reviewed = closed.count()
    return {
        'open_incidents': open_qs.exclude(kind='INDICATOR').count(),
        'critical_open': open_qs.filter(severity='CRITICAL').count(),
        'high_open': open_qs.filter(severity='HIGH').count(),
        'indicators_today': Incident.objects.filter(kind='INDICATOR', detected_at__gte=start).count(),
        'incidents_today': Incident.objects.filter(detected_at__gte=start).exclude(kind='INDICATOR').count(),
        'events_today': Event.objects.filter(occurred_at__gte=start).count(),
        'employees_monitored': Employee.objects.filter(status='ACTIVE').count(),
        'agents_online': sum(1 for a in Agent.objects.filter(revoked=False) if a.online),
        'agents_total': Agent.objects.filter(revoked=False).count(),
        'precision': round(100 * (reviewed - false_pos) / reviewed, 1) if reviewed else None,
        'reviewed': reviewed,
        'server_time': now.isoformat(),
    }


@api_view(['GET'])
@permission_classes([IsAdminOrComplianceOfficer])
def live(request):
    """Polled every 2 seconds by the console. Returns what changed since the last poll."""
    since = _since(request)
    now = timezone.now()
    incidents = Incident.objects.select_related('employee', 'rule').annotate(event_count=Count('events'))
    events = Event.objects.select_related('employee', 'catalogue_entry', 'data_subject')
    new_ids = set()
    if since:
        # Later polls: only what changed. The first poll (no since) returns the latest rows to fill the screen.
        # A row written by another request just before `now` may commit just after this poll ran, so the window
        # overlaps the previous one by a few seconds; the console merges rows by id, so repeats are harmless.
        overlap = since - LIVE_OVERLAP
        incidents = incidents.filter(updated_at__gt=overlap)
        events = events.filter(received_at__gt=overlap)
        new_ids = set(Incident.objects.filter(detected_at__gt=since).values_list('id', flat=True)[:50])
    incidents = incidents.order_by('-updated_at')[:50]
    events = events.order_by('-occurred_at')[:50]
    agents = Agent.objects.filter(revoked=False)
    data = IncidentListSerializer(incidents, many=True).data
    for item in data:
        item['is_new'] = item['id'] in {str(i) for i in new_ids}
    return Response({
        'server_time': now.isoformat(),
        'incidents': data,
        'events': EventSerializer(events, many=True).data,
        'kpis': kpis(),
        'agents': AgentSerializer(agents, many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAdminOrComplianceOfficer])
def overview(request):
    days = 14
    today = timezone.localdate()
    start, _ = day_bounds(today - timedelta(days=days - 1))
    per_day = {}
    for inc in Incident.objects.filter(detected_at__gte=start).exclude(kind='INDICATOR').values('detected_at', 'severity'):
        day = timezone.localtime(inc['detected_at']).date().isoformat()
        bucket = per_day.setdefault(day, {'LOW': 0, 'MEDIUM': 0, 'HIGH': 0, 'CRITICAL': 0})
        bucket[inc['severity']] += 1
    series = []
    for i in range(days):
        day = (today - timedelta(days=days - 1 - i)).isoformat()
        series.append({'day': day, **per_day.get(day, {'LOW': 0, 'MEDIUM': 0, 'HIGH': 0, 'CRITICAL': 0})})

    articles = {}
    for arts in Incident.objects.exclude(kind='INDICATOR').exclude(status='FALSE_POSITIVE').values_list('articles', flat=True):
        for article in arts:
            articles[article] = articles.get(article, 0) + 1
    by_article = sorted(({'article': k, 'count': v} for k, v in articles.items()), key=lambda x: -x['count'])

    return Response({
        'kpis': kpis(),
        'incidents_per_day': series,
        'by_article': by_article[:12],
        'employees': employee_risk_rows()[:8],
    })


def employee_risk_rows():
    week = timezone.now() - timedelta(days=7)
    today = timezone.localdate()
    ai_today = {a.employee_id: a for a in AiDayScore.objects.filter(day=today, employee__isnull=False)}
    rows = []
    for emp in Employee.objects.prefetch_related('accounts').annotate(
        open_incidents=Count('incidents', filter=~Q(incidents__status__in=Incident.CLOSED_STATUSES)
                             & ~Q(incidents__kind='INDICATOR'), distinct=True),
        week_violations=Count('incidents', filter=Q(incidents__detected_at__gte=week, incidents__kind='VIOLATION')
                              & ~Q(incidents__status='FALSE_POSITIVE'), distinct=True),
        max_score=Max('incidents__score', filter=~Q(incidents__status__in=Incident.CLOSED_STATUSES)),
        last_event=Max('events__occurred_at'),
    ):
        ai = ai_today.get(emp.id)
        rows.append({
            'id': str(emp.id),
            'full_name': emp.full_name,
            'employee_code': emp.employee_code,
            'department': emp.department,
            'role': emp.get_role_display(),
            'employment_type': emp.employment_type,
            'status': emp.status,
            'open_incidents': emp.open_incidents,
            'week_violations': emp.week_violations,
            'repeat_offender': emp.week_violations >= 3,
            'risk_score': emp.max_score or 0,
            'ai_score_today': ai.score if ai else None,
            'ai_reason_today': ai.reason if ai else '',
            'last_activity': emp.last_event,
            'accounts': [a.account for a in emp.accounts.all()],
            'max_sensitivity': emp.max_sensitivity,
            'allowed_categories': emp.allowed_categories,
            'shift': f"{emp.shift_start:%H:%M}-{emp.shift_end:%H:%M}",
            'work_days': emp.work_days,
        })
    rows.sort(key=lambda r: (-(r['risk_score'] or 0), -(r['ai_score_today'] or 0)))
    return rows


class IncidentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdminOrComplianceOfficer]
    pagination_class = Pages

    def get_queryset(self):
        qs = Incident.objects.select_related('employee', 'rule').annotate(event_count=Count('events'))
        params = self.request.query_params
        if params.get('status') == 'open':
            qs = qs.exclude(status__in=Incident.CLOSED_STATUSES)
        elif params.get('status'):
            qs = qs.filter(status=params['status'])
        for field in ('severity', 'kind'):
            if params.get(field):
                qs = qs.filter(**{field: params[field]})
        if params.get('employee'):
            qs = qs.filter(employee_id=params['employee'])
        if params.get('rule'):
            qs = qs.filter(rule_codes__icontains=f'"{params["rule"]}"')
        if params.get('article'):
            qs = qs.filter(articles__icontains=f'"{params["article"]}"')
        if params.get('q'):
            q = params['q']
            qs = qs.filter(Q(title__icontains=q) | Q(summary__icontains=q) | Q(account__icontains=q)
                           | Q(employee__full_name__icontains=q))
        if params.get('hide_indicators') == '1':
            qs = qs.exclude(kind='INDICATOR')
        return qs.order_by('-detected_at')

    def get_serializer_class(self):
        return IncidentDetailSerializer if self.action == 'retrieve' else IncidentListSerializer

    def retrieve(self, request, *args, **kwargs):
        incident = self.get_object()
        data = IncidentDetailSerializer(incident).data
        anchor = incident.events.order_by('occurred_at').first()
        timeline = []
        if anchor and (incident.employee_id or incident.account):
            qs = Event.objects.filter(
                occurred_at__gte=anchor.occurred_at - timedelta(minutes=30),
                occurred_at__lte=anchor.occurred_at + timedelta(minutes=30),
            )
            qs = qs.filter(employee_id=incident.employee_id) if incident.employee_id else qs.filter(account=incident.account)
            evidence_ids = set(incident.events.values_list('id', flat=True))
            for item in EventSerializer(qs.select_related('employee', 'catalogue_entry', 'data_subject')
                                        .order_by('occurred_at')[:200], many=True).data:
                item['is_evidence'] = item['id'] in {str(i) for i in evidence_ids}
                timeline.append(item)
        data['timeline'] = timeline
        if incident.employee_id:
            data['employee_detail'] = EmployeeSerializer(incident.employee).data
        return Response(data)

    @action(detail=True, methods=['post'])
    def act(self, request, pk=None):
        incident = self.get_object()
        name = str(request.data.get('action', '')).upper()
        note = str(request.data.get('note', ''))[:2000]
        if name not in ACTION_STATUS:
            return Response({'error': f'Unknown action {name}.'}, status=status.HTTP_400_BAD_REQUEST)
        if name in ('FALSE_POSITIVE', 'RESOLVE') and not note.strip():
            return Response({'error': 'Add a note explaining the decision.'}, status=status.HTTP_400_BAD_REQUEST)
        new_status = ACTION_STATUS[name]
        if new_status:
            incident.status = new_status
        if name in ('INVESTIGATE', 'ACKNOWLEDGE') and not incident.assigned_to_id:
            incident.assigned_to = request.user
        incident.save()
        IncidentAction.objects.create(incident=incident, actor=request.user, action=name, note=note)
        audit(request, f'incident.{name.lower()}', f'INC-{incident.number}', note=note)
        return Response(IncidentDetailSerializer(incident).data)

    @action(detail=True, methods=['post'], url_path='report-lost-device')
    def report_lost_device(self, request, pk=None):
        incident = self.get_object()
        note = str(request.data.get('note', '')).strip()
        breach = BreachRecord.objects.create(
            incident=incident,
            title=f'Lost removable device with personal data (INC-{incident.number})',
            description=note or incident.summary,
            severity='CRITICAL' if incident.severity == 'CRITICAL' else 'HIGH',
            high_risk=True,
        )
        incident.status = 'ESCALATED'
        incident.save()
        IncidentAction.objects.create(incident=incident, actor=request.user, action='REPORT_LOST_DEVICE',
                                      note=note or f'Breach record opened, authority deadline '
                                                   f'{timezone.localtime(breach.notification_deadline):%d %b %H:%M}.')
        audit(request, 'breach.create', breach.title, incident=incident.number)
        return Response(BreachRecordSerializer(breach).data, status=status.HTTP_201_CREATED)


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdminOrComplianceOfficer]
    pagination_class = Pages
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = Event.objects.select_related('employee', 'catalogue_entry', 'data_subject')
        params = self.request.query_params
        if params.get('type'):
            qs = qs.filter(event_type__in=params['type'].split(','))
        if params.get('employee'):
            qs = qs.filter(employee_id=params['employee'])
        if params.get('account'):
            qs = qs.filter(account__iexact=params['account'])
        if params.get('category'):
            qs = qs.filter(category=params['category'])
        if params.get('outside_shift') == '1':
            qs = qs.filter(outside_shift=True)
        since = _since(self.request)
        if since:
            qs = qs.filter(occurred_at__gte=since)
        if params.get('q'):
            q = params['q']
            qs = qs.filter(Q(path__icontains=q) | Q(account__icontains=q) | Q(domain__icontains=q)
                           | Q(device__icontains=q) | Q(employee__full_name__icontains=q))
        return qs.order_by('-occurred_at')


class EmployeeDirectoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only directory for officers (admins edit employees in the admin API)."""

    permission_classes = [IsAdminOrComplianceOfficer]
    serializer_class = EmployeeSerializer
    queryset = Employee.objects.select_related('login').prefetch_related('accounts', 'agents')

    def list(self, request, *args, **kwargs):
        return Response(employee_risk_rows())

    def retrieve(self, request, *args, **kwargs):
        emp = self.get_object()
        data = EmployeeSerializer(emp).data
        since = timezone.localdate() - timedelta(days=13)
        data['ai_days'] = list(AiDayScore.objects.filter(employee=emp, day__gte=since).order_by('day').values(
            'day', 'score', 'reason', 'baseline', 'features', 'contributions'))
        data['incidents'] = IncidentListSerializer(
            emp.incidents.select_related('rule').annotate(event_count=Count('events')).order_by('-detected_at')[:50],
            many=True).data
        data['recent_events'] = EventSerializer(
            emp.events.select_related('catalogue_entry', 'data_subject').order_by('-occurred_at')[:50], many=True).data
        row = next((r for r in employee_risk_rows() if r['id'] == str(emp.id)), None)
        data['risk'] = row
        return Response(data)


class RecordViewSet(AuditedModelMixin, viewsets.ModelViewSet):
    permission_classes = [IsAdminOrComplianceOfficer]


class DataSubjectViewSet(RecordViewSet):
    audit_label = 'data_subject'
    serializer_class = DataSubjectSerializer
    queryset = DataSubject.objects.prefetch_related('consents', 'requests')


class ConsentViewSet(RecordViewSet):
    audit_label = 'consent'
    serializer_class = ConsentRecordSerializer
    queryset = ConsentRecord.objects.select_related('data_subject')


class RequestViewSet(RecordViewSet):
    audit_label = 'dsr'
    serializer_class = DataSubjectRequestSerializer
    queryset = DataSubjectRequest.objects.select_related('data_subject')


class BreachViewSet(RecordViewSet):
    audit_label = 'breach'
    serializer_class = BreachRecordSerializer
    queryset = BreachRecord.objects.select_related('incident')


class ProcessingActivityViewSet(RecordViewSet):
    audit_label = 'ropa'
    serializer_class = ProcessingActivitySerializer
    queryset = ProcessingActivity.objects.all()


class DecisionViewSet(AuditedModelMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminOrComplianceOfficer]
    audit_label = 'decision'
    serializer_class = AutomatedDecisionSerializer
    queryset = AutomatedDecision.objects.all()

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        decision = self.get_object()
        decision.reviewed_by = request.user.get_full_name() or request.user.username
        decision.reviewed_at = timezone.now()
        decision.save()
        audit(request, 'decision.review', decision.decision, subject=decision.subject_reference)
        return Response(AutomatedDecisionSerializer(decision).data)


@api_view(['GET', 'PUT'])
@permission_classes([IsAdminOrComplianceOfficer])
def dpo(request):
    record = DPORecord.objects.order_by('-updated_at').first() or DPORecord.objects.create()
    if request.method == 'PUT':
        serializer = DPORecordSerializer(record, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit(request, 'dpo.update', record, status=record.compliance_status)
    return Response(DPORecordSerializer(record).data)
