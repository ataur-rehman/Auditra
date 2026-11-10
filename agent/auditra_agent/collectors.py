"""Collectors: read Windows sources and turn them into small, structured events.

Nothing else leaves the machine: no raw event logs, no full browsing history, no file contents.

    security   Security log: logons, unlocks, failed logons, lock, account/group/audit-policy changes, log
               cleared, scheduled tasks, file access (4663) inside the catalogue folders
    usb        Plug and Play log: USB storage connected
    usb_copy   watches removable drives; a new file is matched to its source in the catalogue folders
    print      PrintService log: documents printed
    web        Chrome / Edge / Brave history: only visits to the watched file-sharing and social-media domains

Each collector reads its own bookmark from ``agent.state`` and moves it only after a read succeeded. The runner
stores the new bookmarks in the outbox in the same transaction as the events, so a bookmark never gets ahead of
the events it covers.
"""
import ctypes
import os
import queue
import re
import shutil
import socket
import sqlite3
import string
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    import win32api
    import win32evtlog
    import win32file
    import win32security
    import win32ts
except ImportError as exc:  # pragma: no cover - the agent only runs on Windows
    raise SystemExit(f'pywin32 is required: pip install pywin32 ({exc})')

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # USB copy detection is optional
    Observer = None
    FileSystemEventHandler = object

from .log import log

SOURCE_READ_WINDOW = 180  # seconds: a copy to USB is attributed to whoever read the source file just before
MACHINE = socket.gethostname()
NS = '{http://schemas.microsoft.com/win/2004/08/events/event}'
# On the very first round after install, look back this far so the install session itself is visible.
FIRST_RUN_LOOKBACK_MS = 600_000
MAX_RECORDS_PER_ROUND = 2000  # after a long outage the rest is read in the next rounds

SECURITY = 'Security'
PNP = 'Microsoft-Windows-Kernel-PnP/Configuration'
PRINT = 'Microsoft-Windows-PrintService/Operational'
SECURITY_IDS = [4624, 4625, 4663, 4698, 4719, 4720, 4732, 4740, 4800, 1102]

IGNORED_USERS = {'system', 'local service', 'network service', 'anonymous logon', '-', ''}
IGNORED_DOMAINS = {'window manager', 'font driver host', 'nt authority', 'nt service'}
INTERACTIVE_LOGON_TYPES = {2, 7, 10, 11}
# Processes that touch files without a person asking for it.
BACKGROUND_PROCESSES = {
    'msmpeng.exe', 'searchprotocolhost.exe', 'searchindexer.exe', 'searchfilterhost.exe', 'dllhost.exe',
    'svchost.exe', 'onedrive.exe', 'mssense.exe', 'nissrv.exe', 'compattelrunner.exe', 'tiworker.exe',
    'backgroundtaskhost.exe', 'runtimebroker.exe', 'smartscreen.exe', 'python.exe', 'pythonw.exe',
    'auditraagent.exe',
}
# Explorer reads files to draw thumbnails and previews; its deletes and renames are real user actions.
READ_ONLY_IGNORED_PROCESSES = {'explorer.exe', 'prevhost.exe'}
IGNORED_FILE_NAMES = {'desktop.ini', 'thumbs.db'}
FILE_DEDUPE_SECONDS = 60
LOGON_DEDUPE_SECONDS = 5

DELETE_MASK = 0x10000
WRITE_MASKS = 0x2 | 0x4
READ_MASK = 0x1


# ------------------------------------------------------------------ helpers
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def iso_local(aware):
    return aware.astimezone().isoformat()


def system_time(root):
    created = root.find(f'.//{NS}TimeCreated')
    # e.g. 2026-10-22T18:51:25.1234567Z: always UTC, up to 7 fractional digits (Python accepts 6).
    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?', created.attrib['SystemTime'])
    stamp = match.group(1) + (f'.{match.group(2)[:6]}' if match.group(2) else '')
    return datetime.fromisoformat(stamp).replace(tzinfo=dt_timezone.utc)


def event_fields(root):
    """All <Data Name="..."> values plus UserData leaf elements, by name."""
    fields = {}
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        if tag == 'Data' and node.attrib.get('Name'):
            fields[node.attrib['Name']] = (node.text or '').strip()
        elif len(node) == 0 and node.text and tag not in ('Data',):
            fields.setdefault(tag, node.text.strip())
    return fields


def system_value(root, tag):
    node = root.find(f'.//{NS}System/{NS}{tag}')
    return node.text if node is not None else None


def account_of(domain, user):
    user = (user or '').strip()
    domain = (domain or '').strip() or MACHINE
    return f'{domain}\\{user}'


def ignored_account(domain, user):
    user_l = (user or '').strip().lower()
    return (
        user_l in IGNORED_USERS or user_l.endswith('$') or user_l.startswith(('dwm-', 'umfd-'))
        or (domain or '').strip().lower() in IGNORED_DOMAINS
    )


def console_account():
    """The person signed in at this PC's screen, even when the caller runs elevated or as SYSTEM. '' if none."""
    try:
        session = win32ts.WTSGetActiveConsoleSessionId()
        user = win32ts.WTSQuerySessionInformation(None, session, win32ts.WTSUserName)
        domain = win32ts.WTSQuerySessionInformation(None, session, win32ts.WTSDomainName)
        if user:
            return account_of(domain or MACHINE, user)
    except Exception:
        pass
    user = os.environ.get('USERNAME', '')
    if not user or user.endswith('$'):  # running as SYSTEM with nobody signed in
        return ''
    return account_of(MACHINE, user)


def device_account(agent):
    """Windows does not record who plugs in a USB stick, so device events go to the laptop's owner (set at
    enrolment), else to whoever is signed in at the screen."""
    return agent.device_owner or console_account() or account_of(MACHINE, 'unknown')


def sid_to_name(sid_text):
    try:
        sid = win32security.ConvertStringSidToSid(sid_text)
        name, domain, _ = win32security.LookupAccountSid(None, sid)
        return f'{domain}\\{name}'
    except Exception:
        return sid_text


def under_any(path, prefixes):
    p = (path or '').replace('/', '\\').rstrip('\\').lower()
    return any(p == pre or p.startswith(pre + '\\') for pre in prefixes)


class Deduper:
    def __init__(self):
        self.seen = {}

    def fresh(self, key, seconds):
        now = time.monotonic()
        last = self.seen.get(key)
        self.seen[key] = now
        if len(self.seen) > 5000:
            cutoff = now - 600
            self.seen = {k: v for k, v in self.seen.items() if v > cutoff}
        return last is None or now - last > seconds


# ------------------------------------------------------------------ event-log collectors
def query_channel(channel, event_ids, state, key):
    """New events of the given IDs since the last record this agent saw, oldest first."""
    ids = ' or '.join(f'EventID={i}' for i in event_ids)
    last = state[key]
    if last:
        xpath = f'*[System[({ids}) and EventRecordID > {int(last)}]]'
    else:
        xpath = f'*[System[({ids}) and TimeCreated[timediff(@SystemTime) <= {FIRST_RUN_LOOKBACK_MS}]]]'
    handle = win32evtlog.EvtQuery(channel, win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryForwardDirection,
                                  xpath)
    roots = []
    mark = int(last or 0)
    while len(roots) < MAX_RECORDS_PER_ROUND:
        batch = win32evtlog.EvtNext(handle, 100)
        if not batch:
            break
        for record in batch:
            root = ET.fromstring(win32evtlog.EvtRender(record, win32evtlog.EvtRenderEventXml))
            roots.append(root)
            mark = max(mark, int(system_value(root, 'EventRecordID') or 0))
    # The bookmark moves only after the whole read succeeded; the runner persists it together with the events.
    if mark:
        state[key] = mark
    return roots


class SecurityCollector:
    name = 'security'

    def __init__(self, agent):
        self.agent = agent
        self.dedupe = Deduper()

    def collect(self):
        out = []
        for root in query_channel(SECURITY, SECURITY_IDS, self.agent.state, 'bookmark_security'):
            try:
                event = self.parse(root)
            except Exception as exc:
                log(f'  skipped a Security record: {exc}')
                event = None
            if event:
                out.append(event)
        return out

    def base(self, root, event_type, account, event_id):
        record = system_value(root, 'EventRecordID')
        return {
            'type': event_type,
            'occurred_at': iso_local(system_time(root)),
            'account': account,
            'machine': MACHINE,
            'source': 'Security',
            'source_event_id': event_id,
            'key': f'security:{record}',
        }

    def parse(self, root):
        event_id = int(system_value(root, 'EventID'))
        f = event_fields(root)

        if event_id in (4624, 4625):
            user, domain = f.get('TargetUserName'), f.get('TargetDomainName')
            if ignored_account(domain, user):
                return None
            logon_type = int(f.get('LogonType') or 0)
            if event_id == 4624 and logon_type not in INTERACTIVE_LOGON_TYPES:
                return None
            if event_id == 4624:
                event_type = 'UNLOCK' if logon_type == 7 else 'LOGON'
                if not self.dedupe.fresh(('logon', user.lower(), event_type), LOGON_DEDUPE_SECONDS):
                    return None
            else:
                event_type = 'LOGON_FAILED'
            event = self.base(root, event_type, account_of(domain, user), event_id)
            event['logon_type'] = logon_type
            ip = f.get('IpAddress')
            if ip and ip not in ('-', '::1', '127.0.0.1'):
                event['source_ip'] = ip
            if event_id == 4625:
                event['details'] = {'status': f.get('Status'), 'sub_status': f.get('SubStatus')}
            return event

        if event_id == 4800:
            user, domain = f.get('TargetUserName'), f.get('TargetDomainName')
            if ignored_account(domain, user):
                return None
            return self.base(root, 'LOCK', account_of(domain, user), event_id)

        if event_id == 4663:
            return self.parse_file_access(root, f)

        subject_user, subject_domain = f.get('SubjectUserName'), f.get('SubjectDomainName')
        actor = account_of(subject_domain, subject_user)
        if event_id == 1102:
            return self.base(root, 'LOG_CLEARED', actor, event_id)
        if ignored_account(subject_domain, subject_user):
            return None
        if event_id == 4720:
            event = self.base(root, 'ACCOUNT_CREATED', actor, event_id)
            event['details'] = {'target_account': account_of(f.get('TargetDomainName'), f.get('TargetUserName'))}
            return event
        if event_id == 4732:
            event = self.base(root, 'GROUP_MEMBER_ADDED', actor, event_id)
            member = f.get('MemberName')
            if not member or member == '-':
                member = sid_to_name(f.get('MemberSid', ''))
            event['details'] = {'group': f.get('TargetUserName'), 'member': member}
            return event
        if event_id == 4740:
            event = self.base(root, 'ACCOUNT_LOCKED', account_of(MACHINE, f.get('TargetUserName')), event_id)
            event['details'] = {'caller': f.get('TargetDomainName')}
            return event
        if event_id == 4719:
            event = self.base(root, 'AUDIT_POLICY_CHANGED', actor, event_id)
            event['details'] = {'subcategory': f.get('SubcategoryGuid') or f.get('SubcategoryId'),
                                'changes': f.get('AuditPolicyChanges')}
            return event
        if event_id == 4698:
            task = f.get('TaskName') or ''
            # Windows makes these itself (\Microsoft\..., \SoftLanding\<SID>\...); only user-made tasks matter.
            if task.lower().startswith(('\\microsoft\\', '\\softlanding\\')):
                return None
            event = self.base(root, 'TASK_CREATED', actor, event_id)
            event['details'] = {'task_name': task}
            return event
        return None

    def parse_file_access(self, root, f):
        path = f.get('ObjectName') or ''
        if f.get('ObjectType') not in (None, '', 'File'):
            return None
        if not under_any(path, self.agent.catalogue_paths):
            return None
        name = path.split('\\')[-1]
        if not name or name.lower() in IGNORED_FILE_NAMES or name.startswith(('~$', '.~')) or name.endswith('.tmp'):
            return None
        if os.path.isdir(path):
            return None
        user, domain = f.get('SubjectUserName'), f.get('SubjectDomainName')
        if ignored_account(domain, user):
            return None
        # Remember who last touched this file (Explorer included) so a copy to USB can be attributed to them.
        self.agent.recent_access[path.lower()] = (account_of(domain, user), time.monotonic())
        process = f.get('ProcessName') or ''
        process_name = process.split('\\')[-1].lower()
        if process_name in BACKGROUND_PROCESSES:
            return None
        try:
            mask = int(f.get('AccessMask') or '0', 16)
        except ValueError:
            return None
        if mask & DELETE_MASK:
            event_type = 'FILE_DELETE'
        elif mask & WRITE_MASKS:
            event_type = 'FILE_WRITE'
        elif mask & READ_MASK:
            if process_name in READ_ONLY_IGNORED_PROCESSES:
                return None
            event_type = 'FILE_READ'
        else:
            return None
        if not self.dedupe.fresh((user.lower(), path.lower(), event_type), FILE_DEDUPE_SECONDS):
            return None
        event = self.base(root, event_type, account_of(domain, user), 4663)
        event.update({'path': path, 'file_name': name, 'process': process})
        return event


class UsbCollector:
    name = 'usb'

    def __init__(self, agent):
        self.agent = agent
        self.dedupe = Deduper()

    def collect(self):
        out = []
        for root in query_channel(PNP, [410], self.agent.state, 'bookmark_pnp'):
            device = event_fields(root).get('DeviceInstanceId', '')
            if not device.upper().startswith('USBSTOR\\'):
                continue
            if not self.dedupe.fresh(device.lower(), 30):
                continue
            out.append({
                'type': 'USB_CONNECTED',
                'occurred_at': iso_local(system_time(root)),
                'account': device_account(self.agent),
                'machine': MACHINE,
                'device': friendly_device(device),
                'details': {'device_instance': device},
                'source': PNP,
                'source_event_id': 410,
                'key': f'pnp:{system_value(root, "EventRecordID")}',
            })
        return out


def friendly_device(instance):
    """USBSTOR\\Disk&Ven_SanDisk&Prod_Cruzer_Blade&Rev_1.00\\... -> 'SanDisk Cruzer Blade'"""
    try:
        parts = instance.split('\\')[1].split('&')
        vendor = next((p[4:] for p in parts if p.lower().startswith('ven_')), '')
        product = next((p[5:] for p in parts if p.lower().startswith('prod_')), '')
        return f'{vendor} {product}'.replace('_', ' ').strip() or instance
    except IndexError:
        return instance


class PrintCollector:
    name = 'print'

    def __init__(self, agent):
        self.agent = agent

    def collect(self):
        out = []
        for root in query_channel(PRINT, [307], self.agent.state, 'bookmark_print'):
            f = event_fields(root)
            document = f.get('Param2', '')
            user = f.get('Param3', '')
            source = self.agent.index.match_document(document)
            event = {
                'type': 'PRINT',
                'occurred_at': iso_local(system_time(root)),
                'account': account_of(MACHINE, user) if user else device_account(self.agent),
                'machine': MACHINE,
                'file_name': document[:255],
                'details': {'printer': f.get('Param5', ''), 'pages': f.get('Param8', '')},
                'source': PRINT,
                'source_event_id': 307,
                'key': f'print:{system_value(root, "EventRecordID")}',
            }
            if source:
                event['path'] = source
                event['details']['source_path'] = source
            out.append(event)
        return out


# ------------------------------------------------------------------ catalogue index and USB copies
class CatalogueIndex:
    """File name + size -> path for every file in the catalogue folders, to recognise copies on USB."""

    def __init__(self):
        self.by_name_size = {}
        self.by_name = {}
        self.files = []
        self.lock = threading.Lock()

    def rebuild(self, prefixes):
        by_name_size, by_name, files = {}, {}, []
        for prefix in prefixes:
            if not os.path.exists(prefix):
                continue
            if os.path.isfile(prefix):
                walk = [(os.path.dirname(prefix), [], [os.path.basename(prefix)])]
            else:
                walk = os.walk(prefix)
            for folder, dirs, names in walk:
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for name in names:
                    path = os.path.join(folder, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    by_name_size[(name.lower(), stat.st_size)] = path
                    by_name.setdefault(name.lower(), path)
                    files.append((path, stat.st_size, stat.st_mtime))
        with self.lock:
            self.by_name_size, self.by_name, self.files = by_name_size, by_name, files

    def match(self, name, size):
        with self.lock:
            return self.by_name_size.get((name.lower(), size)) or self.by_name.get(name.lower())

    def match_document(self, document):
        doc = (document or '').lower()
        with self.lock:
            for name, path in self.by_name.items():
                if name in doc:
                    return path
        return None


def removable_drives():
    drives = []
    mask = win32api.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f'{letter}:\\'
            try:
                if win32file.GetDriveType(root) == win32file.DRIVE_REMOVABLE:
                    drives.append(root)
            except Exception:
                continue
    return drives


class _UsbHandler(FileSystemEventHandler):
    def __init__(self, pending):
        self.pending = pending

    def on_created(self, event):
        if not event.is_directory:
            self.pending.put(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.pending.put(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.pending.put(event.dest_path)


class UsbCopyCollector:
    name = 'usb_copy'

    def __init__(self, agent):
        self.agent = agent
        self.pending = queue.Queue()
        self.watched = {}
        self.waiting = {}
        self.reported = Deduper()

    def refresh_watches(self):
        if Observer is None:
            return
        current = set(removable_drives())
        for drive in list(self.watched):
            if drive not in current:
                try:
                    self.watched.pop(drive).stop()
                except Exception:
                    pass
        for drive in current - set(self.watched):
            observer = Observer()
            observer.schedule(_UsbHandler(self.pending), drive, recursive=True)
            observer.daemon = True
            try:
                observer.start()
                self.watched[drive] = observer
                log(f'  watching removable drive {drive}')
            except Exception as exc:
                log(f'  cannot watch {drive}: {exc}')

    def collect(self):
        self.refresh_watches()
        while True:
            try:
                path = self.pending.get_nowait()
            except queue.Empty:
                break
            self.waiting[path] = time.monotonic()
        out = []
        for path, seen in list(self.waiting.items()):
            if time.monotonic() - seen < 4:
                continue
            self.waiting.pop(path)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            name = os.path.basename(path)
            if name.lower() in IGNORED_FILE_NAMES or name.startswith('~$'):
                continue
            if not self.reported.fresh((path.lower(), size), 120):
                continue
            source = self.agent.index.match(name, size)
            reader = self.agent.recent_access.get(source.lower()) if source else None
            if reader and time.monotonic() - reader[1] <= SOURCE_READ_WINDOW:
                account = reader[0]
            else:
                account = device_account(self.agent)
            event = {
                'type': 'FILE_COPY_TO_USB',
                'occurred_at': iso_local(datetime.now(dt_timezone.utc)),
                'account': account,
                'machine': MACHINE,
                'path': path,
                'file_name': name,
                'device': path[:2],
                'details': {'size': size},
                'source': 'USB file watcher',
                'key': f'usbcopy:{path.lower()}:{size}:{int(time.time() // 120)}',
            }
            if source:
                event['details']['source_path'] = source
            out.append(event)
        return out


# ------------------------------------------------------------------ browser history
CHROMIUM_ROOTS = [r'Google\Chrome\User Data', r'Microsoft\Edge\User Data', r'BraveSoftware\Brave-Browser\User Data']
EPOCH_1601 = datetime(1601, 1, 1, tzinfo=dt_timezone.utc)


class WebCollector:
    name = 'web'

    def __init__(self, agent):
        self.agent = agent

    def history_files(self):
        users_root = Path(os.environ.get('SystemDrive', 'C:') + '\\Users')
        for user_dir in users_root.iterdir() if users_root.exists() else []:
            local = user_dir / 'AppData' / 'Local'
            for browser in CHROMIUM_ROOTS:
                base = local / browser
                if not base.exists():
                    continue
                for profile in base.iterdir():
                    history = profile / 'History'
                    if profile.is_dir() and history.is_file():
                        yield user_dir.name, browser.split('\\')[1], history

    def category(self, host):
        host = host.lower().split(':')[0]
        for category, domains in self.agent.watched_domains.items():
            for domain in domains:
                if host == domain or host.endswith('.' + domain):
                    return category, domain
        return None, None

    def collect(self):
        out = []
        marks = self.agent.state['web_marks'] or {}
        now_mark = int((datetime.now(dt_timezone.utc) - EPOCH_1601).total_seconds() * 1_000_000)
        for user, browser, history in self.history_files():
            key = str(history).lower()
            since = marks.get(key, now_mark)
            copy = Path(tempfile.gettempdir()) / f'auditra_hist_{abs(hash(key))}.db'
            try:
                shutil.copy2(history, copy)
                with sqlite3.connect(f'file:{copy}?mode=ro', uri=True) as db:
                    rows = db.execute(
                        'SELECT urls.url, visits.visit_time FROM visits JOIN urls ON urls.id = visits.url '
                        'WHERE visits.visit_time > ? ORDER BY visits.visit_time LIMIT 500', (since,)
                    ).fetchall()
            except Exception:
                marks[key] = since
                continue
            finally:
                try:
                    copy.unlink()
                except OSError:
                    pass
            latest = since
            for url, visit_time in rows:
                latest = max(latest, visit_time)
                host = urlparse(url).hostname or ''
                category, domain = self.category(host)
                if not category:
                    continue
                when = EPOCH_1601 + timedelta(microseconds=visit_time)
                out.append({
                    'type': 'WEB_VISIT',
                    'occurred_at': iso_local(when),
                    'account': account_of(MACHINE, user),
                    'machine': MACHINE,
                    'domain': domain,
                    'details': {'site_category': category, 'browser': browser, 'host': host},
                    'source': f'{browser} history',
                    'key': f'web:{key}:{visit_time}',
                })
            marks[key] = latest
        self.agent.state['web_marks'] = marks
        return out
