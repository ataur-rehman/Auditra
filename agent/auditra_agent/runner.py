"""The agent's main loop: collect, store in the outbox, send, heartbeat, keep Windows configured.

Collection never waits for the network. Every round's events go into the outbox first; sending happens after and
backs off while the server is unreachable. When the server comes back, the backlog is sent oldest first.
"""
import time
from datetime import datetime, timezone as dt_timezone

import requests

from . import VERSION, winconfig
from .collectors import (
    MACHINE, CatalogueIndex, Observer, PrintCollector, SecurityCollector, UsbCollector, UsbCopyCollector,
    WebCollector, console_account, is_admin,
)
from .log import log
from .outbox import Outbox, drain
from .paths import OUTBOX, load_config, save_config

CHECK_EVERY = 300  # seconds between full Windows configuration checks
MAX_BACKOFF = 60


class TokenRejected(Exception):
    pass


class State:
    """Bookmarks and marks the collectors keep between rounds. Persisted only together with the events."""

    def __init__(self, data):
        self.data = dict(data or {})

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value


class Server:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.headers['User-Agent'] = f'AuditraAgent/{VERSION}'

    @property
    def base(self):
        return self.config['server']

    def register_with_key(self):
        """LAN demo only: the shared key registers a machine that was not enrolled with a code."""
        response = self.session.post(f'{self.base}/api/agent/register/', json={
            'hostname': MACHINE, 'enrolment_key': self.config['enrolment_key'], 'version': VERSION,
            'is_admin': is_admin(), 'console_user': console_account(),
        }, timeout=15)
        if response.status_code != 200:
            raise TokenRejected(f'registration refused: {response.status_code} {response.text[:200]}')
        self.config['token'] = response.json()['token']
        save_config(self.config)
        log(f'Registered with {self.base} as {MACHINE} using the shared key')

    def post(self, path, payload, timeout=30):
        if not self.config.get('token'):
            if self.config.get('enrolment_key'):
                self.register_with_key()
            else:
                raise TokenRejected('This laptop is not enrolled. Run AuditraAgent.exe with an enrolment code.')
        response = self.session.post(f'{self.base}{path}', json=payload, timeout=timeout,
                                     headers={'X-Agent-Token': self.config['token']})
        if response.status_code == 401:
            if self.config.get('enrolment_key'):
                self.register_with_key()
                response = self.session.post(f'{self.base}{path}', json=payload, timeout=timeout,
                                             headers={'X-Agent-Token': self.config['token']})
            else:
                raise TokenRejected('The server no longer accepts this laptop (revoked or enrolled again). '
                                    'Events are kept locally until it is enrolled again.')
        response.raise_for_status()
        return response.json()


class Agent:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.config = load_config()
        self.server = Server(self.config)
        self.outbox = Outbox(OUTBOX)
        self.state = State(self.outbox.get('state', {}))
        self.server_config = self.outbox.get('server_config', {})
        self.catalogue_paths = []
        self.watched_domains = {}
        self.inventory_minutes = 10
        self.interval = 3
        self.device_owner = ''
        self.index = CatalogueIndex()
        self.collectors = []
        self.health = {}
        self.checks = {}
        self.audit_policy = winconfig.AuditPolicy()
        self.recent_access = {}
        self.last_inventory = 0.0
        self.last_index = 0.0
        self.last_checks = 0.0
        self.next_send = 0.0
        self.backoff = 2
        self.failures_5xx = 0
        self.stuck = {}
        self.server_ok = False
        self.clock_drift = None
        if self.server_config:
            self.apply_config(self.server_config, startup=True)

    # ---------------------------------------------------------------- configuration from the server
    def apply_config(self, config, startup=False):
        paths = sorted(config.get('catalogue_paths', []))
        changed = paths != self.catalogue_paths
        if changed:
            self.catalogue_paths = paths
            self.last_index = 0
            self.last_checks = 0
            log(f'  catalogue folders: {", ".join(paths) or "none yet (add them in Admin > Data Catalogue)"}')
        self.watched_domains = config.get('watched_domains', {})
        self.inventory_minutes = int(config.get('inventory_minutes', 10))
        self.interval = max(1, int(config.get('interval_seconds', 3)))
        self.device_owner = config.get('device_owner', '') or ''
        if config.get('server_time'):
            try:
                server_now = datetime.fromisoformat(config['server_time'])
                self.clock_drift = (datetime.now(dt_timezone.utc) - server_now).total_seconds()
            except ValueError:
                pass
        if not startup:
            self.server_config = config
            self.outbox.put('server_config', config)

    def start(self):
        readable = winconfig.security_log_readable()
        print_banner(self.config, readable, self.device_owner)
        self.collectors = [UsbCollector(self), UsbCopyCollector(self), PrintCollector(self), WebCollector(self)]
        if readable['ok']:
            self.collectors.insert(0, SecurityCollector(self))
        else:
            log(f'Security log {readable["detail"]}: logons and file access will not be collected')
        if Observer is None:
            log('watchdog is not installed: copies to USB will not be detected')

    # ---------------------------------------------------------------- Windows configuration
    def configure_windows(self):
        cfg = self.server_config or {}
        checks = {'security_log': winconfig.security_log_readable()}
        try:
            checks['audit_policy'] = self.audit_policy.ensure(cfg.get('required_audit', {}))
        except Exception as exc:
            checks['audit_policy'] = winconfig.check(False, f'error: {exc}', 'Run the agent as SYSTEM.')
        for name, step in (('print_log', winconfig.ensure_print_log),
                           ('security_log_size', winconfig.ensure_security_log_size)):
            try:
                checks[name] = step()
            except Exception as exc:
                checks[name] = winconfig.check(False, f'error: {exc}')
        try:
            result, added = winconfig.ensure_file_auditing(self.catalogue_paths, self.outbox.get('sacl_added', []))
            self.outbox.put('sacl_added', added)
            checks['file_auditing'] = result
        except Exception as exc:
            checks['file_auditing'] = winconfig.check(False, f'error: {exc}')
        notice = cfg.get('notice') or {}
        if notice.get('caption'):
            try:
                previous = winconfig.set_sign_in_notice(notice['caption'], notice['text'],
                                                        self.outbox.get('notice_backup'))
                if self.outbox.get('notice_backup') is None:
                    self.outbox.put('notice_backup', previous)
                checks['sign_in_notice'] = winconfig.sign_in_notice_check(notice['caption'])
            except Exception as exc:
                checks['sign_in_notice'] = winconfig.check(False, f'error: {exc}')
        if self.clock_drift is not None:
            drift = round(self.clock_drift)
            checks['clock'] = winconfig.check(abs(drift) < 120, f'{drift:+d} s from the server',
                                              'Sync the Windows clock (Settings > Time > Sync now).')
        self.checks = checks
        bad = [f'{k}: {v["detail"]}' for k, v in checks.items() if not v['ok']]
        if bad:
            log('  Windows checks need attention: ' + '; '.join(bad))
        self.last_checks = time.monotonic()

    # ---------------------------------------------------------------- one round
    def collect(self):
        if time.monotonic() - self.last_index > 300:
            self.index.rebuild(self.catalogue_paths)
            self.last_index = time.monotonic()
        events = []
        for collector in self.collectors:
            try:
                found = collector.collect()
                self.health[collector.name] = 'ok'
                events.extend(found)
            except Exception as exc:
                self.health[collector.name] = f'error: {str(exc)[:120]}'
                log(f'  {collector.name}: {exc}')
        if events and self.verbose:
            for event in events:
                target = event.get('path') or event.get('domain') or event.get('device') or ''
                log(f'  > {event["type"]:<20} {event["account"]:<28} {target}')
        # Events and the bookmarks that cover them are stored together (see outbox.py).
        self.outbox.commit_round(events, self.state.data)
        return len(events)

    def report(self, result, _events):
        log(f'  sent {result["stored"]} event(s), {result["duplicates"]} duplicate(s), '
            f'{result["incidents_created"]} new incident(s)')
        for incident in result.get('incidents', []):
            log(f'    INC-{incident["number"]} {incident["severity"]} {incident["score"]} {incident["title"]}')
        for problem in result.get('rejected', []):
            log(f'    rejected #{problem["index"]}: {problem["error"]}')

    def send(self):
        if time.monotonic() < self.next_send or not self.outbox.pending():
            return
        batch = 1 if self.failures_5xx >= 5 else 400
        sent, error = drain(self.outbox, lambda events: self.server.post('/api/agent/events/', {'events': events}),
                            report=self.report, batch=batch)
        if error is None:
            self.backoff, self.failures_5xx, self.stuck = 2, 0, {}
            return
        self.fail(error)
        status = getattr(getattr(error, 'response', None), 'status_code', 0) or 0
        if status >= 500:
            self.failures_5xx += 1
            if batch == 1:
                # The server keeps failing on this one event: set it aside so it does not block the rest.
                head = self.outbox.peek(1)
                if head:
                    row_id = head[0][0]
                    self.stuck[row_id] = self.stuck.get(row_id, 0) + 1
                    if self.stuck[row_id] >= 3:
                        self.outbox.quarantine(row_id, f'HTTP {status}')
                        log(f'  set aside one event the server cannot store (HTTP {status})')
                        self.stuck.pop(row_id, None)

    def fail(self, error):
        if isinstance(error, requests.exceptions.ConnectionError):
            message = f'cannot reach {self.server.base}'
        elif isinstance(error, requests.exceptions.Timeout):
            message = f'{self.server.base} timed out'
        else:
            message = str(error)[:200]
        if self.server_ok or self.backoff >= MAX_BACKOFF or self.backoff == 2:
            log(f'  {message}; {self.outbox.pending()} event(s) kept locally, retrying in {self.backoff} s')
        self.server_ok = False
        self.next_send = time.monotonic() + self.backoff
        self.backoff = min(self.backoff * 2, MAX_BACKOFF)

    def inventory(self):
        if time.monotonic() - self.last_inventory < self.inventory_minutes * 60 or not self.index.files:
            return
        files = [{'path': path, 'size': size, 'modified_at': datetime.fromtimestamp(mtime).astimezone().isoformat()}
                 for path, size, mtime in self.index.files]
        result = self.server.post('/api/agent/inventory/', {'files': files, 'account': console_account()})
        if result.get('over_retention'):
            log(f'  inventory: {result["over_retention"]} file(s) past retention')
        self.last_inventory = time.monotonic()

    def heartbeat(self):
        response = self.server.post('/api/agent/heartbeat/', {
            'version': VERSION, 'is_admin': is_admin(), 'console_user': console_account(),
            'collectors': self.health, 'checks': self.checks, 'outbox': self.outbox.pending(),
        }, timeout=15)
        if not self.server_ok:
            log(f'Connected to {self.server.base}')
        self.server_ok = True
        self.apply_config(response['config'])

    def round(self):
        if not self.collectors:
            self.start()
        if time.monotonic() - self.last_checks > CHECK_EVERY:
            self.configure_windows()
        self.collect()
        self.send()
        if time.monotonic() >= self.next_send:
            try:
                self.heartbeat()
                self.inventory()
                if self.outbox.pending():
                    self.send()
            except TokenRejected as exc:
                log(f'  {exc}')
                self.fail(exc)
            except requests.RequestException as exc:
                self.fail(exc)

    def run(self, stop_event):
        log(f'Auditra agent {VERSION} started on {MACHINE}')
        while not stop_event.is_set():
            try:
                self.round()
            except Exception as exc:  # the loop must survive anything
                log(f'error: {exc}')
            stop_event.wait(self.interval)
        self.outbox.close()
        log('Auditra agent stopped')


def print_banner(config, readable, owner):
    log('=' * 64)
    log(f'  Auditra agent {VERSION}')
    log(f'  Machine : {MACHINE}')
    log(f'  Server  : {config["server"]}')
    log(f'  Enrolled: {"yes" if config.get("token") else "no (shared key)" if config.get("enrolment_key") else "NO"}')
    log(f'  Security: {readable["detail"]}')
    log(f'  User    : {console_account() or "nobody signed in"}')
    if owner:
        log(f'  Owner   : {owner} (USB plug-ins are attributed to this account)')
    log('=' * 64)
