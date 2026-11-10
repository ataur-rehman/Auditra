from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .api import admin, agent, auth, me, officer, reports
from .tokens import AuditraTokenObtainPairView

router = DefaultRouter()
router.register('incidents', officer.IncidentViewSet, basename='incident')
router.register('events', officer.EventViewSet, basename='event')
router.register('employees', officer.EmployeeDirectoryViewSet, basename='employee')
router.register('records/subjects', officer.DataSubjectViewSet, basename='subject')
router.register('records/consents', officer.ConsentViewSet, basename='consent')
router.register('records/requests', officer.RequestViewSet, basename='request')
router.register('records/breaches', officer.BreachViewSet, basename='breach')
router.register('records/processing', officer.ProcessingActivityViewSet, basename='processing')
router.register('records/decisions', officer.DecisionViewSet, basename='decision')
router.register('catalogue', admin.CatalogueViewSet, basename='catalogue')
router.register('rules', admin.RuleViewSet, basename='rule')
router.register('admin/users', admin.UserViewSet, basename='admin-user')
router.register('admin/employees', admin.EmployeeViewSet, basename='admin-employee')
router.register('admin/agents', admin.AgentViewSet, basename='admin-agent')
router.register('admin/audit', admin.AuditViewSet, basename='admin-audit')

urlpatterns = [
    path('auth/login/', AuditraTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', auth.logout, name='logout'),
    path('auth/me/', auth.me, name='me'),
    path('health/', auth.health, name='health'),

    path('agent/register/', agent.register, name='agent-register'),
    path('agent/enrol/', agent.enrol, name='agent-enrol'),
    path('agent/heartbeat/', agent.heartbeat, name='agent-heartbeat'),
    path('agent/events/', agent.events, name='agent-events'),
    path('agent/inventory/', agent.inventory, name='agent-inventory'),
    path('decisions/', agent.automated_decision, name='decisions-ingest'),

    path('me/portal/', me.portal, name='me-portal'),
    path('me/notice/ack/', me.acknowledge_notice, name='me-notice-ack'),
    path('me/enrolment-codes/', me.enrolment_code, name='me-enrolment-code'),

    path('live/', officer.live, name='live'),
    path('overview/', officer.overview, name='overview'),
    path('records/dpo/', officer.dpo, name='dpo'),
    path('reports/compliance.pdf', reports.compliance_report, name='compliance-report'),

    path('admin/unlinked-accounts/', admin.unlinked_accounts, name='unlinked-accounts'),
    path('admin/health/', admin.health, name='admin-health'),
    path('admin/reset-monitoring/', admin.reset_monitoring, name='reset-monitoring'),

    path('', include(router.urls)),
]
