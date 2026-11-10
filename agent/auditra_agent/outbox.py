"""A local SQLite outbox, so no event is lost when the server cannot be reached.

Each round, the events a round collected and the bookmarks that cover them are written in one transaction.
The sender deletes an event only after the server answered 200 for its batch. If the server is down, returns 5xx,
or the network drops, the events stay and are sent later, oldest first. The server drops repeats by each event's
key, so sending a batch twice is harmless.
"""
import json
import sqlite3
import threading
import time

BATCH = 400
MAX_ROWS = 200_000


class Outbox:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                        'payload TEXT NOT NULL, created REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.dropped = 0

    # ---------------------------------------------------------------- key/value (bookmarks, cached config)
    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM kv WHERE key = ?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)', (key, json.dumps(value)))

    # ---------------------------------------------------------------- events
    def commit_round(self, events, state):
        """Store a round's events and its bookmarks together, or neither."""
        now = time.time()
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.executemany('INSERT INTO events (payload, created) VALUES (?, ?)',
                                    [(json.dumps(e), now) for e in events])
                self.db.execute('INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)', ('state', json.dumps(state)))
                count = self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
                if count > MAX_ROWS:
                    # Months offline: keep the newest events rather than fill the disk.
                    extra = count - MAX_ROWS
                    self.db.execute('DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id LIMIT ?)',
                                    (extra,))
                    self.dropped += extra
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise

    def pending(self):
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]

    def peek(self, limit=BATCH):
        with self.lock:
            rows = self.db.execute('SELECT id, payload FROM events ORDER BY id LIMIT ?', (limit,)).fetchall()
        return [(row_id, json.loads(payload)) for row_id, payload in rows]

    def ack(self, ids):
        if not ids:
            return
        with self.lock:
            self.db.executemany('DELETE FROM events WHERE id = ?', [(i,) for i in ids])

    def quarantine(self, row_id, reason):
        """Move one event the server keeps failing on (HTTP 5xx when sent alone) out of the queue, so it cannot
        block everything behind it. It is kept in the dead table for inspection."""
        with self.lock:
            self.db.execute('CREATE TABLE IF NOT EXISTS dead (id INTEGER PRIMARY KEY, payload TEXT, reason TEXT, '
                            'at REAL)')
            self.db.execute('INSERT OR REPLACE INTO dead (id, payload, reason, at) '
                            'SELECT id, payload, ?, ? FROM events WHERE id = ?', (str(reason)[:500], time.time(), row_id))
            self.db.execute('DELETE FROM events WHERE id = ?', (row_id,))

    def close(self):
        with self.lock:
            self.db.close()


def drain(outbox, post, report=None, max_batches=25, batch=BATCH):
    """Send queued events oldest first. ``post(events)`` returns the server's JSON or raises.

    Stops at the first failure and leaves the unsent events in place. Returns (sent, error).
    """
    sent = 0
    for _ in range(max_batches):
        rows = outbox.peek(batch)
        if not rows:
            return sent, None
        try:
            result = post([payload for _, payload in rows])
        except Exception as exc:  # network down, 5xx, timeout: keep everything for the next attempt
            return sent, exc
        # The server answered for the whole batch: stored, duplicates and rejected are all settled.
        outbox.ack([row_id for row_id, _ in rows])
        sent += len(rows)
        if report:
            report(result, [payload for _, payload in rows])
    return sent, None
