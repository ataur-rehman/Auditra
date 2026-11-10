"""The employee's own portal: the monitoring notice, their devices, and a code to enrol a laptop.

An employee login only ever sees data about that employee. Incidents are not shown here: they are an officer's
working material and may concern an investigation in progress.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .. import notice
from ..models import DPORecord, EnrolmentCode, Event
from ..permissions import IsEmployee
from .common import audit


def _acknowledged(employee):
    return bool(employee.notice_acknowledged_at) and employee.notice_version == notice.version()


@api_view(['GET'])
@permission_classes([IsEmployee])
def portal(request):
    employee = request.user.employee
    dpo = DPORecord.objects.first()
    week = timezone.now() - timedelta(days=7)
    collected = (
        Event.objects.filter(employee=employee, occurred_at__gte=week)
        .values('event_type').annotate(count=Count('id')).order_by('-count')
    )
    devices = [
        {'id': str(a.id), 'hostname': a.hostname, 'online': a.online, 'last_seen': a.last_seen,
         'registered_at': a.registered_at, 'version': a.version}
        for a in employee.agents.filter(revoked=False).order_by('hostname')
    ]
    return Response({
        'employee': {
            'full_name': employee.full_name, 'employee_code': employee.employee_code,
            'department': employee.department, 'role': employee.get_role_display(),
            'shift_start': employee.shift_start, 'shift_end': employee.shift_end,
            'accounts': [a.account for a in employee.accounts.all()],
        },
        'notice': notice.as_dict(),
        'acknowledged': _acknowledged(employee),
        'acknowledged_at': employee.notice_acknowledged_at,
        'organisation': dpo.organization_name if dpo else '',
        'dpo': {'name': dpo.name, 'contact': dpo.contact} if dpo and (dpo.name or dpo.contact) else None,
        'devices': devices,
        'collected_7_days': list(collected),
        'download_url': settings.AGENT_DOWNLOAD_URL,
    })


@api_view(['POST'])
@permission_classes([IsEmployee])
def acknowledge_notice(request):
    employee = request.user.employee
    employee.notice_version = notice.version()
    employee.notice_acknowledged_at = timezone.now()
    employee.save(update_fields=['notice_version', 'notice_acknowledged_at'])
    audit(request, 'employee.notice_ack', employee.full_name, version=employee.notice_version)
    return Response({'acknowledged': True, 'acknowledged_at': employee.notice_acknowledged_at})


@api_view(['POST'])
@permission_classes([IsEmployee])
def enrolment_code(request):
    employee = request.user.employee
    if not _acknowledged(employee):
        return Response({'error': 'Read and acknowledge the monitoring notice first.'},
                        status=status.HTTP_400_BAD_REQUEST)
    if employee.status != 'ACTIVE':
        return Response({'error': 'Your employee record is not active.'}, status=status.HTTP_403_FORBIDDEN)
    # One live code at a time: issuing a new one retires the previous unused codes.
    EnrolmentCode.objects.filter(employee=employee, used_at__isnull=True, expires_at__gt=timezone.now()) \
        .update(expires_at=timezone.now())
    record, code = EnrolmentCode.issue(employee, request.user, settings.ENROLMENT_CODE_MINUTES)
    audit(request, 'employee.enrolment_code', employee.full_name, expires_at=record.expires_at.isoformat())
    return Response({'code': code, 'expires_at': record.expires_at}, status=status.HTTP_201_CREATED)
