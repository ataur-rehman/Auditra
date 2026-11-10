"""Employee logins, the monitoring notice, code enrolment, and the production settings guard."""
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ..models import Agent, AuditraUser, EmployeeAccount, EnrolmentCode, Event
from .helpers import MACHINE, build_org, ev, local

BACKEND = Path(__file__).resolve().parents[2]


class EnrolmentTests(TestCase):
    def setUp(self):
        self.org = build_org()
        self.bilal = self.org['bilal']
        self.admin = AuditraUser.objects.create_user('boss', password='Admin@2026', role='admin')
        self.client = APIClient()

    def employee_login(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(f'/api/admin/employees/{self.bilal.id}/login/', {'username': 'bilal'},
                                    format='json')
        self.assertEqual(response.status_code, 201)
        user = AuditraUser.objects.get(username='bilal')
        self.assertEqual((user.role, user.employee_id), ('employee', self.bilal.id))
        self.assertTrue(user.check_password(response.data['password']))
        portal = APIClient()
        portal.force_authenticate(user)
        return portal

    def test_admin_creates_and_resets_an_employee_login(self):
        self.employee_login()
        again = self.client.post(f'/api/admin/employees/{self.bilal.id}/login/', {}, format='json')
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.data['created'])
        self.assertTrue(AuditraUser.objects.get(username='bilal').check_password(again.data['password']))

    def test_employee_cannot_reach_officer_or_admin_endpoints(self):
        portal = self.employee_login()
        for path in ['/api/live/', '/api/overview/', '/api/incidents/', '/api/events/', '/api/employees/',
                     '/api/records/subjects/', '/api/records/dpo/', '/api/catalogue/', '/api/rules/',
                     '/api/admin/users/', '/api/admin/employees/', '/api/admin/agents/', '/api/admin/health/',
                     '/api/admin/unlinked-accounts/', '/api/reports/compliance.pdf']:
            self.assertEqual(portal.get(path).status_code, 403, path)
        self.assertEqual(portal.post('/api/admin/reset-monitoring/', {'confirm': 'RESET'},
                                     format='json').status_code, 403)

    def test_officer_cannot_use_the_employee_portal(self):
        officer = AuditraUser.objects.create_user('officer', password='Officer@2026', role='compliance_officer')
        client = APIClient()
        client.force_authenticate(officer)
        self.assertEqual(client.get('/api/me/portal/').status_code, 403)

    def test_notice_must_be_acknowledged_before_a_code(self):
        portal = self.employee_login()
        data = portal.get('/api/me/portal/').data
        self.assertFalse(data['acknowledged'])
        self.assertTrue(data['notice']['collected'])
        self.assertEqual(data['dpo']['contact'], 'dpo@example.com')
        self.assertEqual(portal.post('/api/me/enrolment-codes/').status_code, 400)
        self.assertEqual(portal.post('/api/me/notice/ack/').status_code, 200)
        self.assertTrue(portal.get('/api/me/portal/').data['acknowledged'])
        issued = portal.post('/api/me/enrolment-codes/')
        self.assertEqual(issued.status_code, 201)
        self.assertRegex(issued.data['code'], r'^[A-Z2-9]{4}-[A-Z2-9]{4}$')
        self.assertFalse(EnrolmentCode.objects.filter(code_hash__icontains=issued.data['code']).exists())

    def test_a_new_notice_version_needs_a_new_acknowledgement(self):
        portal = self.employee_login()
        portal.post('/api/me/notice/ack/')
        with override_settings(MONITORING_NOTICE_VERSION='2'):
            self.assertFalse(portal.get('/api/me/portal/').data['acknowledged'])
            self.assertEqual(portal.post('/api/me/enrolment-codes/').status_code, 400)

    def code(self):
        portal = self.employee_login()
        portal.post('/api/me/notice/ack/')
        return portal.post('/api/me/enrolment-codes/').data['code']

    def test_enrol_links_the_machine_and_the_signed_in_account(self):
        code = self.code()
        # Activity from an unknown account before enrolment moves to Bilal once the laptop is enrolled.
        anon = APIClient()
        Event.objects.create(event_type='LOGON', occurred_at=local(10), machine='LAPTOP7', account=r'LAPTOP7\bilal.a',
                             dedupe_key='pre-enrol', source='test')
        response = anon.post('/api/agent/enrol/', {
            'code': code.lower().replace('-', ''), 'hostname': 'LAPTOP7', 'console_user': r'LAPTOP7\Bilal.A',
            'version': '3.0', 'is_admin': True,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        agent = Agent.objects.get(hostname='LAPTOP7')
        self.assertEqual(agent.employee, self.bilal)
        self.assertEqual(response.data['config']['device_owner'], r'laptop7\bilal.a')
        self.assertIn('File System', response.data['config']['required_audit'])
        self.assertTrue(EmployeeAccount.objects.filter(account=r'laptop7\bilal.a', employee=self.bilal).exists())
        self.assertEqual(Event.objects.get(dedupe_key='pre-enrol').employee, self.bilal)

        anon.credentials(HTTP_X_AGENT_TOKEN=response.data['token'])
        beat = anon.post('/api/agent/heartbeat/', {'checks': {'audit_policy': 'ok'}, 'outbox': 4}, format='json')
        self.assertEqual(beat.status_code, 200)
        agent.refresh_from_db()
        self.assertEqual((agent.checks, agent.outbox), ({'audit_policy': 'ok'}, 4))

    def test_a_code_works_once(self):
        code = self.code()
        anon = APIClient()
        first = anon.post('/api/agent/enrol/', {'code': code, 'hostname': 'LAPTOP7'}, format='json')
        self.assertEqual(first.status_code, 200)
        again = anon.post('/api/agent/enrol/', {'code': code, 'hostname': 'LAPTOP8'}, format='json')
        self.assertEqual(again.status_code, 403)

    def test_an_expired_or_wrong_code_is_refused(self):
        code = self.code()
        EnrolmentCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        anon = APIClient()
        self.assertEqual(anon.post('/api/agent/enrol/', {'code': code, 'hostname': 'L1'},
                                   format='json').status_code, 403)
        self.assertEqual(anon.post('/api/agent/enrol/', {'code': 'AAAA-BBBB', 'hostname': 'L1'},
                                   format='json').status_code, 403)

    def test_admin_can_issue_a_code_without_an_employee_login(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(f'/api/admin/employees/{self.bilal.id}/enrolment-code/')
        self.assertEqual(response.status_code, 201)
        enrolled = APIClient().post('/api/agent/enrol/', {'code': response.data['code'], 'hostname': MACHINE},
                                    format='json')
        self.assertEqual(enrolled.status_code, 200)

    def test_shared_key_cannot_take_over_an_enrolled_machine(self):
        code = self.code()
        APIClient().post('/api/agent/enrol/', {'code': code, 'hostname': MACHINE}, format='json')
        taken = APIClient().post('/api/agent/register/', {'hostname': MACHINE,
                                                          'enrolment_key': 'auditra-ingest-dev-key'}, format='json')
        self.assertEqual(taken.status_code, 409)

    @override_settings(AGENT_KEY_ENROLMENT=False)
    def test_shared_key_registration_can_be_turned_off(self):
        response = APIClient().post('/api/agent/register/', {'hostname': 'X',
                                                             'enrolment_key': 'auditra-ingest-dev-key'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_portal_shows_what_was_collected_about_the_employee(self):
        portal = self.employee_login()
        from ..ingest import ingest_events
        ingest_events([ev('LOGON', local(10))])
        rows = portal.get('/api/me/portal/').data['collected_7_days']
        self.assertEqual(rows, [{'event_type': 'LOGON', 'count': 1}])

    def test_public_health_check(self):
        self.assertEqual(APIClient().get('/api/health/').data, {'ok': True})


class ProductionSettingsTests(TestCase):
    def run_settings(self, **env):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ('DEBUG', 'SECRET_KEY', 'INGEST_API_KEY', 'ALLOWED_HOSTS', 'RAILWAY_ENVIRONMENT')}
        clean.update(env)
        clean['DB_ENGINE'] = 'sqlite'
        # settings.py reads ../.env with setdefault, so values set here win over the developer's file.
        return subprocess.run(
            [sys.executable, '-c', 'import django, os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", '
                                   '"auditra.settings"); django.setup(); print("ok")'],
            cwd=BACKEND, env=clean, capture_output=True, text=True, timeout=60,
        )

    def test_production_refuses_the_development_secrets(self):
        result = self.run_settings(DEBUG='false', SECRET_KEY='auditra-secret-key-2026-change-in-production',
                                   ALLOWED_HOSTS='api.example.com')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SECRET_KEY', result.stderr)

    def test_production_starts_with_real_secrets(self):
        result = self.run_settings(DEBUG='false', SECRET_KEY='x' * 50, INGEST_API_KEY='y' * 40,
                                   ALLOWED_HOSTS='api.example.com')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_railway_defaults_to_debug_off(self):
        result = self.run_settings(RAILWAY_ENVIRONMENT='production', RAILWAY_PUBLIC_DOMAIN='a.up.railway.app')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SECRET_KEY', result.stderr)


class DeviceStatusTests(TestCase):
    def test_working_attention_and_offline(self):
        build_org()
        agent = Agent.objects.create(hostname='L1', token=Agent.new_token(), last_seen=timezone.now(),
                                     collectors={'security': 'ok'}, checks={'audit_policy': {'ok': True}})
        self.assertEqual((agent.state, agent.problems), ('working', []))
        agent.checks = {'audit_policy': {'ok': False, 'detail': 'x'}}
        self.assertEqual(agent.state, 'attention')
        self.assertEqual(agent.problems, ['Windows auditing is off'])
        agent.last_seen = timezone.now() - timedelta(minutes=5)
        self.assertEqual(agent.state, 'offline')

    def test_portal_and_admin_show_the_device_state(self):
        org = build_org()
        Agent.objects.create(hostname='L1', token=Agent.new_token(), last_seen=timezone.now(), employee=org['bilal'],
                             checks={'file_auditing': {'ok': False}})
        user = AuditraUser.objects.create_user('bilal', password='x' * 12, role='employee', employee=org['bilal'])
        admin = AuditraUser.objects.create_user('boss', password='x' * 12, role='admin')
        portal, console = APIClient(), APIClient()
        portal.force_authenticate(user)
        console.force_authenticate(admin)
        device = portal.get('/api/me/portal/').data['devices'][0]
        self.assertEqual((device['state'], device['problems']), ('attention', ['File auditing is missing']))
        row = next(e for e in console.get('/api/admin/employees/').data if e['full_name'] == 'Bilal Ahmed')
        self.assertEqual(row['devices'][0]['state'], 'attention')
        health = console.get('/api/admin/health/').data
        self.assertIn('download_url', health)
        self.assertEqual(health['agents'][0]['state'], 'attention')
