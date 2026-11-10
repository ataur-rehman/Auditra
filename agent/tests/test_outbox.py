"""The outbox must never lose an event: server down, 5xx, rejected events, restarts."""
import shutil
import tempfile
import unittest
from pathlib import Path

from auditra_agent.outbox import Outbox, drain


class FakeServer:
    def __init__(self):
        self.down = False
        self.status = 200
        self.received = []

    def post(self, events):
        if self.down:
            raise ConnectionError('server unreachable')
        if self.status >= 500:
            error = RuntimeError(f'HTTP {self.status}')
            error.response = type('R', (), {'status_code': self.status})()
            raise error
        self.received.extend(events)
        return {'stored': len(events), 'duplicates': 0, 'rejected': [], 'incidents_created': 0}


def events(n, start=0):
    return [{'type': 'FILE_READ', 'key': f'k{i}'} for i in range(start, start + n)]


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / 'outbox.db'
        self.box = Outbox(self.path)
        self.server = FakeServer()

    def tearDown(self):
        self.box.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_events_wait_while_the_server_is_down_and_arrive_in_order(self):
        self.server.down = True
        self.box.commit_round(events(3), {'bookmark_security': 10})
        sent, error = drain(self.box, self.server.post)
        self.assertEqual((sent, self.box.pending()), (0, 3))
        self.assertIsNotNone(error)
        self.box.commit_round(events(2, start=3), {'bookmark_security': 12})
        self.server.down = False
        sent, error = drain(self.box, self.server.post)
        self.assertIsNone(error)
        self.assertEqual(sent, 5)
        self.assertEqual([e['key'] for e in self.server.received], ['k0', 'k1', 'k2', 'k3', 'k4'])
        self.assertEqual(self.box.pending(), 0)

    def test_a_server_error_keeps_the_batch(self):
        self.box.commit_round(events(4), {})
        self.server.status = 503
        sent, error = drain(self.box, self.server.post)
        self.assertEqual((sent, self.box.pending()), (0, 4))
        self.server.status = 200
        self.assertEqual(drain(self.box, self.server.post)[0], 4)

    def test_events_and_bookmarks_survive_a_restart_together(self):
        self.box.commit_round(events(2), {'bookmark_security': 42, 'web_marks': {'a': 1}})
        self.box.close()
        reopened = Outbox(self.path)
        try:
            self.assertEqual(reopened.pending(), 2)
            self.assertEqual(reopened.get('state'), {'bookmark_security': 42, 'web_marks': {'a': 1}})
        finally:
            reopened.close()
        self.box = Outbox(self.path)

    def test_a_failed_commit_stores_neither_events_nor_bookmarks(self):
        self.box.commit_round(events(1), {'bookmark_security': 1})
        with self.assertRaises(TypeError):
            self.box.commit_round([{'bad': object()}], {'bookmark_security': 99})
        self.assertEqual(self.box.pending(), 1)
        self.assertEqual(self.box.get('state'), {'bookmark_security': 1})

    def test_large_backlog_goes_in_batches(self):
        self.box.commit_round(events(1000), {})
        sent, _ = drain(self.box, self.server.post, batch=400)
        self.assertEqual(sent, 1000)
        self.assertEqual(len(self.server.received), 1000)

    def test_quarantine_moves_one_event_aside(self):
        self.box.commit_round(events(2), {})
        row_id = self.box.peek(1)[0][0]
        self.box.quarantine(row_id, 'HTTP 500')
        self.assertEqual([p['key'] for _, p in self.box.peek()], ['k1'])


if __name__ == '__main__':
    unittest.main()
