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
