import unittest
import xml.etree.ElementTree as ET

try:
    from auditra_agent import collectors as agent
except SystemExit:  # pywin32 missing (not Windows)
    agent = None

NS = 'http://schemas.microsoft.com/win/2004/08/events/event'


def record(system_time, data=None):
    fields = ''.join(f'<Data Name="{k}">{v}</Data>' for k, v in (data or {}).items())
    return ET.fromstring(
        f'<Event xmlns="{NS}"><System><EventID>4663</EventID><EventRecordID>7</EventRecordID>'
        f'<TimeCreated SystemTime="{system_time}"/></System><EventData>{fields}</EventData></Event>'
    )


@unittest.skipIf(agent is None, 'agent needs pywin32')
class AgentParsingTests(unittest.TestCase):
    def test_windows_utc_time_becomes_aware_utc(self):
        moment = agent.system_time(record('2026-10-22T18:51:25.1234567Z'))
        self.assertEqual(moment.utcoffset().total_seconds(), 0)
        self.assertEqual((moment.hour, moment.minute, moment.second), (18, 51, 25))

    def test_named_fields(self):
        fields = agent.event_fields(record('2026-10-22T18:51:25Z', {'SubjectUserName': 'bilal', 'AccessMask': '0x1'}))
        self.assertEqual(fields['SubjectUserName'], 'bilal')
        self.assertEqual(fields['AccessMask'], '0x1')

    def test_friendly_device(self):
        self.assertEqual(agent.friendly_device(r'USBSTOR\Disk&Ven_SanDisk&Prod_Cruzer_Blade&Rev_1.00\4C53'),
                         'SanDisk Cruzer Blade')


@unittest.skipIf(agent is None, 'agent needs pywin32')
class AccountResolverTests(unittest.TestCase):
    LOCAL = r'CRAZY\ataur'

    def test_microsoft_account_logon_uses_the_local_name_from_its_sid(self):
        resolver = agent.AccountResolver(lookup=lambda: {}, resolve_sid=lambda sid: self.LOCAL)
        self.assertEqual(resolver.account('MicrosoftAccount', 'ali@outlook.com', 'S-1-5-21-1-2-3-1001'), self.LOCAL)

    def test_failed_logon_without_a_sid_uses_the_local_account_list(self):
        resolver = agent.AccountResolver(lookup=lambda: {'ali@outlook.com': self.LOCAL}, resolve_sid=lambda sid: sid)
        self.assertEqual(resolver.account('MicrosoftAccount', 'Ali@Outlook.com', 'S-1-0-0'), self.LOCAL)

    def test_local_and_domain_accounts_are_unchanged(self):
        resolver = agent.AccountResolver(lookup=lambda: {}, resolve_sid=lambda sid: r'X\y')
        self.assertEqual(resolver.account('CRAZY', 'bilal', 'S-1-5-21-1'), r'CRAZY\bilal')

    def test_unknown_microsoft_account_is_kept_as_is(self):
        resolver = agent.AccountResolver(lookup=lambda: {}, resolve_sid=lambda sid: sid)
        self.assertEqual(resolver.account('MicrosoftAccount', 'x@live.com', 'S-1-0-0'), r'MicrosoftAccount\x@live.com')

    def test_real_lookup_runs(self):
        self.assertIsInstance(agent.online_identities(), dict)
