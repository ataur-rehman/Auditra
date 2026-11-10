from django.conf import settings
from rest_framework.permissions import BasePermission

class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'admin'
        )

class IsComplianceOfficer(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'compliance_officer'
        )

class IsAdminOrComplianceOfficer(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role in ['admin', 'compliance_officer']
        )


class IsIngestClient(BasePermission):
    """Officer/admin JWT, or the shared ingest key used by the Windows agent."""

    message = 'A compliance JWT or a valid X-Auditra-Ingest-Key is required.'

    def has_permission(self, request, view):
        user = request.user
        if (
            user
            and user.is_authenticated
            and getattr(user, 'role', None) in ('admin', 'compliance_officer')
        ):
            return True
        expected = getattr(settings, 'INGEST_API_KEY', '')
        provided = request.headers.get('X-Auditra-Ingest-Key', '')
        return bool(expected) and provided == expected

class IsEmployee(BasePermission):
    """A monitored employee's own login: only their portal (/api/me/...)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.role == 'employee' and user.employee_id
        )
