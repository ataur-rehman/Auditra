"""Endpoints used by the Windows agent and by business systems."""
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response

from .. import notice
from ..ingest import analyse_events, ingest_events
from ..models import (
    Agent, AuditEntry, AutomatedDecision, CatalogueEntry, DataSubject, EnrolmentCode, Event, hash_enrolment_code,
    normalize_path,
)

MAX_BATCH = 500

# Audit subcategories the agent turns on and checks. GUIDs are language independent.
REQUIRED_AUDIT = {
    'Logon': '{0CCE9215-69AE-11D9-BED3-505054503030}',
    'Other Logon/Logoff Events': '{0CCE921C-69AE-11D9-BED3-505054503030}',
    'Account Lockout': '{0CCE9217-69AE-11D9-BED3-505054503030}',
    'File System': '{0CCE921D-69AE-11D9-BED3-505054503030}',
    'Other Object Access Events': '{0CCE9227-69AE-11D9-BED3-505054503030}',
    'User Account Management': '{0CCE9235-69AE-11D9-BED3-505054503030}',
    'Security Group Management': '{0CCE9237-69AE-11D9-BED3-505054503030}',
    'Audit Policy Change': '{0CCE922F-69AE-11D9-BED3-505054503030}',
}

# Only visits to these domains leave the employee's machine (data minimisation).
WATCHED_DOMAINS = {
    'FILE_SHARING': [
        'drive.google.com', 'docs.google.com', 'dropbox.com', 'wetransfer.com', 'we.tl', 'mega.nz', 'box.com',
        'onedrive.live.com', '1drv.ms', 'mediafire.com', 'file.io', 'filebin.net', 'gofile.io', 'sendgb.com',
        'mail.google.com', 'outlook.live.com', 'mail.yahoo.com',
    ],
    'SOCIAL_MEDIA': [
        'facebook.com', 'instagram.com', 'x.com', 'twitter.com', 'tiktok.com', 'reddit.com', 'snapchat.com',
        'youtube.com', 'web.whatsapp.com', 'linkedin.com',
    ],
}


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', ''))[:50]


def _enrolment_key_ok(provided):
    expected = getattr(settings, 'INGEST_API_KEY', '')
    return bool(expected) and hmac.compare_digest(str(provided or ''), expected)


class AgentTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.headers.get('X-Agent-Token', '')
        if not token:
            return None
        agent = Agent.objects.filter(token=token).first()
        if agent is None or agent.revoked:
            raise AuthenticationFailed('Unknown or revoked agent token. Register the agent again.')
        return (None, agent)

    def authenticate_header(self, request):
        return 'X-Agent-Token'


class IsAgent(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, Agent)


def _touch(agent, request, data=None):
    data = data or {}
    agent.last_seen = timezone.now()
    agent.ip_address = _client_ip(request)
    for field in ('version', 'console_user'):
        if data.get(field) is not None:
            setattr(agent, field, str(data[field])[:150])
    if data.get('is_admin') is not None:
        agent.is_admin = bool(data['is_admin'])
    if isinstance(data.get('collectors'), dict):
        agent.collectors = data['collectors']
    if isinstance(data.get('checks'), dict):
        agent.checks = data['checks']
    if isinstance(data.get('outbox'), int) and data['outbox'] >= 0:
        agent.outbox = data['outbox']
    agent.save()


def _device_owner(agent):
    """The account USB plug-ins are attributed to: the owner's account on this machine, else their first one."""
    if agent is None or agent.employee_id is None:
        return ''
    accounts = [a.account for a in agent.employee.accounts.all()]
    on_machine = [a for a in accounts if a.split('\\')[0] == agent.hostname.lower()]
    return (on_machine or accounts or [''])[0]


def agent_config(agent=None):
    return {
        'catalogue_paths': sorted({e.path_prefix for e in CatalogueEntry.objects.all()}),
        'subject_paths': sorted({s.path_prefix for s in DataSubject.objects.exclude(path_prefix='')}),
        'watched_domains': WATCHED_DOMAINS,
        'interval_seconds': int(getattr(settings, 'AGENT_INTERVAL_SECONDS', 3)),
        'inventory_minutes': int(getattr(settings, 'AGENT_INVENTORY_MINUTES', 10)),
        'device_owner': _device_owner(agent),
        'required_audit': REQUIRED_AUDIT,
        'notice': {'caption': notice.CAPTION, 'text': notice.WINDOWS_TEXT, 'version': notice.version()},
        'server_time': timezone.now().isoformat(),
    }


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    """Shared-key registration, for the LAN demo only. Production agents enrol with a one-time code."""
    if not getattr(settings, 'AGENT_KEY_ENROLMENT', False):
        return Response({'error': 'Registration with the shared key is turned off. Enrol this laptop with a '
                                  'one-time code from the Auditra console.'}, status=status.HTTP_403_FORBIDDEN)
    if not _enrolment_key_ok(request.data.get('enrolment_key') or request.headers.get('X-Auditra-Ingest-Key')):
        return Response({'error': 'Invalid enrolment key.'}, status=status.HTTP_403_FORBIDDEN)
    hostname = str(request.data.get('hostname') or '').strip()[:100]
    if not hostname:
        return Response({'error': 'hostname is required.'}, status=status.HTTP_400_BAD_REQUEST)
    agent = Agent.objects.filter(hostname__iexact=hostname).first()
    if agent and agent.revoked:
        return Response({'error': 'This machine was revoked by an administrator.'}, status=status.HTTP_403_FORBIDDEN)
    if agent and agent.employee_id:
        # A machine enrolled to an employee keeps its token; the shared key must not take it over.
        return Response({'error': 'This machine is enrolled to an employee. Enrol it again with a new code.'},
                        status=status.HTTP_409_CONFLICT)
    if agent is None:
        agent = Agent(hostname=hostname)
    agent.token = Agent.new_token()
    _touch(agent, request, request.data)
    return Response({'agent_id': str(agent.id), 'token': agent.token, 'config': agent_config(agent)})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def enrol(request):
    """The installer enrols a laptop with a one-time code issued to one employee.

    The machine gets its own token, the employee becomes the device owner, and the Windows account signed in at the
    console is linked to the employee (with its recent activity moved to them).
    """
    from .admin import AccountTaken, link_account

    code = str(request.data.get('code') or '')
    hostname = str(request.data.get('hostname') or '').strip()[:100]
    console_user = str(request.data.get('console_user') or '').strip()[:150]
    if not code or not hostname:
        return Response({'error': 'code and hostname are required.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        record = (EnrolmentCode.objects.select_for_update().select_related('employee')
                  .filter(code_hash=hash_enrolment_code(code)).first())
        if record is None or not record.usable:
            return Response({'error': 'This enrolment code is wrong, expired or already used. Ask for a new one.'},
                            status=status.HTTP_403_FORBIDDEN)
        employee = record.employee
        if employee.status != 'ACTIVE':
            return Response({'error': f'{employee.full_name} is no longer active.'}, status=status.HTTP_403_FORBIDDEN)
        agent = Agent.objects.filter(hostname__iexact=hostname).first()
        if agent and agent.revoked:
            return Response({'error': 'This machine was revoked by an administrator.'},
                            status=status.HTTP_403_FORBIDDEN)
        if agent is None:
            agent = Agent(hostname=hostname)
        agent.token = Agent.new_token()
        agent.employee = employee
        _touch(agent, request, request.data)
        record.used_at = timezone.now()
        record.agent = agent
        record.save(update_fields=['used_at', 'agent'])
    linked = None
    if '\\' in console_user:
        try:
            _, result = link_account(console_user, employee)
            linked = {'account': console_user.lower(), **result}
        except AccountTaken as exc:
            linked = {'account': console_user.lower(), 'error': str(exc)}
    AuditEntry.objects.create(actor=None, action='agent.enrol', target=hostname,
                              details={'employee': employee.full_name, 'console_user': console_user,
                                       'linked': linked, 'ip': _client_ip(request)})
    return Response({'agent_id': str(agent.id), 'token': agent.token, 'employee': employee.full_name,
                     'linked': linked, 'config': agent_config(agent)})


@api_view(['POST'])
@authentication_classes([AgentTokenAuthentication])
@permission_classes([IsAgent])
def heartbeat(request):
    _touch(request.auth, request, request.data)
    return Response({'ok': True, 'config': agent_config(request.auth)})


@api_view(['POST'])
@authentication_classes([AgentTokenAuthentication])
@permission_classes([IsAgent])
def events(request):
    agent = request.auth
    raw = request.data.get('events')
    if not isinstance(raw, list):
        return Response({'error': 'events must be a list.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(raw) > MAX_BATCH:
        return Response({'error': f'At most {MAX_BATCH} events per request.'}, status=status.HTTP_400_BAD_REQUEST)
    _touch(agent, request)
    result = ingest_events(raw, agent=agent)
    return Response({
        'stored': result['stored'],
        'duplicates': result['duplicates'],
        'rejected': result['rejected'],
        'incidents_created': result['incidents_created'],
        'incidents': [{'number': i.number, 'title': i.title, 'severity': i.severity, 'score': i.score}
                      for i in result['incidents']],
    })


@api_view(['POST'])
@authentication_classes([AgentTokenAuthentication])
@permission_classes([IsAgent])
def inventory(request):
    """The agent lists files in catalogue folders; files older than their retention period become events."""
    agent = request.auth
    files = request.data.get('files')
    if not isinstance(files, list):
        return Response({'error': 'files must be a list.'}, status=status.HTTP_400_BAD_REQUEST)
    _touch(agent, request)
    entries = [e for e in CatalogueEntry.objects.exclude(retention_days__isnull=True)]
    account = str(request.data.get('account') or f'{agent.hostname}\\system')[:150]
    now = timezone.now()
    created = []
    for item in files[:5000]:
        if not isinstance(item, dict):
            continue
        path = normalize_path(item.get('path'))
        modified = parse_datetime(str(item.get('modified_at') or ''))
        if not path or modified is None:
            continue
        if timezone.is_naive(modified):
            modified = timezone.make_aware(modified)
        entry = None
        for candidate in entries:
            if path == candidate.path_prefix or path.startswith(candidate.path_prefix + '\\'):
                if entry is None or len(candidate.path_prefix) > len(entry.path_prefix):
                    entry = candidate
        if entry is None:
            continue
        age = now - modified
        if age < timedelta(days=entry.retention_days):
            continue
        key = f'retention|{path}|{modified.date().isoformat()}'
        created.append({
            'type': 'RETENTION_EXCEEDED',
            'occurred_at': now.isoformat(),
            'account': account,
            'machine': agent.hostname,
            'path': item.get('path'),
            'details': {'age_days': age.days, 'retention_days': entry.retention_days,
                        'modified_at': modified.isoformat(), 'size': item.get('size')},
            'source': 'Auditra inventory scan',
            'key': key,
        })
    result = ingest_events(created, agent=agent) if created else {'stored': 0, 'incidents_created': 0}
    return Response({'checked': len(files), 'over_retention': len(created), 'stored': result['stored'],
                     'incidents_created': result['incidents_created']})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def automated_decision(request):
    """Business systems report decisions made without a person (Art. 22)."""
    if not _enrolment_key_ok(request.headers.get('X-Auditra-Ingest-Key')):
        return Response({'error': 'Invalid X-Auditra-Ingest-Key.'}, status=status.HTTP_403_FORBIDDEN)
    data = request.data
    system = str(data.get('system') or '').strip()[:100]
    reference = str(data.get('subject_reference') or '').strip()[:100]
    decision = str(data.get('decision') or '').strip()[:200]
    if not (system and reference and decision):
        return Response({'error': 'system, subject_reference and decision are required.'},
                        status=status.HTTP_400_BAD_REQUEST)
    made_at = parse_datetime(str(data.get('made_at') or '')) or timezone.now()
    if timezone.is_naive(made_at):
        made_at = timezone.make_aware(made_at)
    record = AutomatedDecision.objects.create(
        system=system,
        subject_reference=reference,
        data_subject=DataSubject.objects.filter(reference__iexact=reference).first(),
        decision=decision,
        significant_effect=bool(data.get('significant_effect', True)),
        made_at=made_at,
    )
    event = Event.objects.create(
        event_type='AUTOMATED_DECISION', occurred_at=made_at, machine=system, account=f'{system}\\service',
        domain='', details={'decision': decision, 'subject_reference': reference,
                            'significant_effect': record.significant_effect, 'decision_id': str(record.id)},
        data_subject=record.data_subject, source='Decisions API', dedupe_key=f'decision:{record.id}',
    )
    analyse_events([event])
    return Response({'id': str(record.id), 'review_due': (made_at + timedelta(hours=1)).isoformat()},
                    status=status.HTTP_201_CREATED)
