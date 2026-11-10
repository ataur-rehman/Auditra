"""Windows configuration the agent needs, applied and checked by the agent itself (it runs as SYSTEM).

Windows only writes the events Auditra reads when auditing is switched on:
  * the audit policy subcategories (logons, file system, account management, ...),
  * an audit rule (SACL) on every folder in the data catalogue, so opening or deleting a file there is logged,
  * the PrintService log, which is off by default,
  * a Security log large enough that events are not overwritten before they are read.

Each check returns {'ok': bool, 'detail': str, 'fix': str}. The agent reports them in every heartbeat, and the
console shows them on Agents & Health. Group Policy on a company domain can switch a setting back; when a setting
the agent fixed is found off again, the check says so, because only the domain administrator can change it then.
"""
import ctypes
import os
import re
import subprocess
import uuid
import winreg
from ctypes import wintypes

import ntsecuritycon
import win32api
import win32evtlog
import win32security

from .log import log
from .paths import DATA_DIR, NO_WINDOW

PRINT_CHANNEL = 'Microsoft-Windows-PrintService/Operational'
SECURITY_LOG_BYTES = 256 * 1024 * 1024
# Read, write, append and delete: the same rights the demo setup script audits.
AUDIT_MASK = 0x1 | 0x2 | 0x4 | 0x10000
EVERYONE = win32security.ConvertStringSidToSid('S-1-1-0')
NOTICE_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
POLICY_AUDIT_EVENT_SUCCESS = 0x1
INHERITED_ACE = 0x10


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)
    return result.returncode, (result.stdout or '') + (result.stderr or '')


def check(ok, detail, fix=''):
    return {'ok': bool(ok), 'detail': detail, 'fix': '' if ok else fix}


# ------------------------------------------------------------------ privileges
def enable_privilege(name):
    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY)
        luid = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(token, False, [(luid, win32security.SE_PRIVILEGE_ENABLED)])
        return win32api.GetLastError() == 0
    except Exception:
        return False


# ------------------------------------------------------------------ audit policy
class _GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                ('Data4', ctypes.c_ubyte * 8)]


class _AUDIT_POLICY_INFORMATION(ctypes.Structure):
    _fields_ = [('AuditSubCategoryGuid', _GUID), ('AuditingInformation', wintypes.ULONG),
                ('AuditCategoryGuid', _GUID)]


def _guid(text):
    u = uuid.UUID(text)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def audit_success_enabled(guids):
    """{guid: True/False} for 'audit success' on each subcategory, from the language-independent API."""
    enable_privilege(win32security.SE_SECURITY_NAME)  # the query needs SeSecurityPrivilege turned on
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    query = advapi.AuditQuerySystemPolicy
    query.restype = wintypes.BOOLEAN
    query.argtypes = [ctypes.POINTER(_GUID), wintypes.ULONG,
                      ctypes.POINTER(ctypes.POINTER(_AUDIT_POLICY_INFORMATION))]
    array = (_GUID * len(guids))(*[_guid(g) for g in guids])
    out = ctypes.POINTER(_AUDIT_POLICY_INFORMATION)()
    if not query(array, len(guids), ctypes.byref(out)) or not out:
        raise OSError(ctypes.get_last_error(), 'AuditQuerySystemPolicy failed')
    try:
        return {g: bool(out[i].AuditingInformation & POLICY_AUDIT_EVENT_SUCCESS) for i, g in enumerate(guids)}
    finally:
        advapi.AuditFree(out)


class AuditPolicy:
    """Remembers what it fixed, so a setting that comes back off can be reported as overridden by Group Policy."""

    def __init__(self):
        self.fixed = set()

    def ensure(self, required):
        if not required:
            return check(False, 'The server sent no audit policy.', 'Update the Auditra server.')
        names = {guid: name for name, guid in required.items()}
        try:
            state = audit_success_enabled(list(names))
        except OSError as exc:
            return check(False, f'Cannot read the audit policy: {exc}', 'Run the agent as SYSTEM or Administrator.')
        missing = [g for g, on in state.items() if not on]
        reverted = [names[g] for g in missing if g in self.fixed]
        for guid in missing:
            code, output = _run(['auditpol', '/set', f'/subcategory:{guid}', '/success:enable', '/failure:enable'])
            if code == 0:
                self.fixed.add(guid)
            else:
                log(f'  auditpol {names[guid]}: {output.strip()[:160]}')
        still = [names[g] for g, on in audit_success_enabled(list(names)).items() if not on]
        if reverted:
            return check(False, f'Turned off again after the agent fixed it: {", ".join(reverted)}',
                         'Group Policy overrides the local audit policy. Ask the domain administrator to enable '
                         'these subcategories in Advanced Audit Policy.')
        if still:
            return check(False, f'Not enabled: {", ".join(still)}', 'Run AuditraAgent.exe again as Administrator.')
        fixed_now = [names[g] for g in missing]
        detail = f'{len(names)} subcategories on' + (f' (turned on: {", ".join(fixed_now)})' if fixed_now else '')
        return check(True, detail)


def backup_audit_policy():
    target = DATA_DIR / 'auditpol_backup.csv'
    if not target.exists():
        _run(['auditpol', '/backup', f'/file:{target}'])
    return target


def restore_audit_policy():
    target = DATA_DIR / 'auditpol_backup.csv'
    if target.exists():
        code, output = _run(['auditpol', '/restore', f'/file:{target}'])
        return code == 0, output.strip()
    return False, 'no backup'


# ------------------------------------------------------------------ event logs
def _channel_value(channel, key):
    code, output = _run(['wevtutil', 'gl', channel])
    if code != 0:
        return None
    match = re.search(rf'^\s*{key}:\s*(\S+)', output, re.MULTILINE)
    return match.group(1) if match else None


def ensure_print_log():
    if (_channel_value(PRINT_CHANNEL, 'enabled') or '').lower() != 'true':
        _run(['wevtutil', 'sl', PRINT_CHANNEL, '/e:true'])
    on = (_channel_value(PRINT_CHANNEL, 'enabled') or '').lower() == 'true'
    return check(on, 'PrintService log on' if on else 'PrintService log is off',
                 'Run: wevtutil sl Microsoft-Windows-PrintService/Operational /e:true')


def ensure_security_log_size():
    size = int(_channel_value('Security', 'maxSize') or 0)
    if size < SECURITY_LOG_BYTES:
        _run(['wevtutil', 'sl', 'Security', f'/ms:{SECURITY_LOG_BYTES}'])
        size = int(_channel_value('Security', 'maxSize') or 0)
    ok = size >= SECURITY_LOG_BYTES
    return check(ok, f'{size // (1024 * 1024)} MB', 'Run: wevtutil sl Security /ms:268435456')


def security_log_readable():
    try:
        handle = win32evtlog.EvtQuery('Security', win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
                                      '*[System[EventID=4624]]')
        win32evtlog.EvtNext(handle, 1)
        return check(True, 'readable')
    except Exception as exc:
        return check(False, f'cannot read: {exc}', 'The agent must run as SYSTEM (the service) or as Administrator.')


# ------------------------------------------------------------------ file auditing (SACL)
def _sacl(path):
    sd = win32security.GetNamedSecurityInfo(path, win32security.SE_FILE_OBJECT,
                                            win32security.SACL_SECURITY_INFORMATION)
    return sd.GetSecurityDescriptorSacl()


def _covering_ace(sacl):
    """Index of an ACE that audits successful read/write/delete by Everyone, and whether it is inherited."""
    if sacl is None:
        return None, False
    for i in range(sacl.GetAceCount()):
        (ace_type, flags), mask, sid = sacl.GetAce(i)
        if (ace_type == ntsecuritycon.SYSTEM_AUDIT_ACE_TYPE and sid == EVERYONE
                and flags & ntsecuritycon.SUCCESSFUL_ACCESS_ACE_FLAG and mask & AUDIT_MASK == AUDIT_MASK):
            return i, bool(flags & INHERITED_ACE)
    return None, False


def ensure_sacl(path):
    """'ok', 'added', 'absent' (not on this machine) or 'error: ...'."""
    if not os.path.exists(path):
        return 'absent'
    if not enable_privilege(win32security.SE_SECURITY_NAME):
        return 'error: SeSecurityPrivilege not available (run as SYSTEM or Administrator)'
    try:
        sacl = _sacl(path)
        index, _ = _covering_ace(sacl)
        if index is not None:
            return 'ok'
        if sacl is None:
            sacl = win32security.ACL()
        flags = ntsecuritycon.OBJECT_INHERIT_ACE | ntsecuritycon.CONTAINER_INHERIT_ACE if os.path.isdir(path) else 0
        sacl.AddAuditAccessAceEx(win32security.ACL_REVISION_DS, flags, AUDIT_MASK, EVERYONE, True, False)
        win32security.SetNamedSecurityInfo(path, win32security.SE_FILE_OBJECT,
                                            win32security.SACL_SECURITY_INFORMATION, None, None, None, sacl)
        return 'added'
    except Exception as exc:
        return f'error: {exc}'


def remove_sacl(path):
    """Remove the audit rule the agent added (never an inherited one)."""
    if not os.path.exists(path) or not enable_privilege(win32security.SE_SECURITY_NAME):
        return False
    try:
        sacl = _sacl(path)
        index, inherited = _covering_ace(sacl)
        if index is None or inherited:
            return False
        sacl.DeleteAce(index)
        win32security.SetNamedSecurityInfo(path, win32security.SE_FILE_OBJECT,
                                            win32security.SACL_SECURITY_INFORMATION, None, None, None, sacl)
        return True
    except Exception:
        return False


def ensure_file_auditing(paths, added_store):
    """Audit rules on every catalogue path present on this laptop. ``added_store`` remembers what the agent added,
    so uninstall removes only those."""
    statuses = {}
    added = set(added_store or [])
    for path in paths:
        status = ensure_sacl(path)
        statuses[path] = status
        if status == 'added':
            added.add(path)
            log(f'  file auditing turned on for {path}')
    errors = {p: s for p, s in statuses.items() if s.startswith('error')}
    present = [p for p, s in statuses.items() if s != 'absent']
    if not paths:
        result = check(False, 'No folders in the data catalogue yet.', 'Add folders in Admin > Data Catalogue.')
    elif errors:
        result = check(False, f'{len(errors)} folder(s) could not be audited',
                       'Run the agent as SYSTEM; check the folders are on a local NTFS drive.')
    elif not present:
        result = check(False, 'None of the catalogue folders exist on this laptop.',
                       'Check the catalogue paths match this laptop (for example C:\\AuditraCompany\\...).')
    else:
        result = check(True, f'{len(present)} of {len(paths)} catalogue path(s) on this laptop audited')
    result['paths'] = statuses
    return result, sorted(added)


# ------------------------------------------------------------------ Windows sign-in notice
def set_sign_in_notice(caption, text, backup_store):
    """Windows shows this before every sign-in and the person must press OK. Returns the previous values the first
    time, so uninstall can put them back."""
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NOTICE_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        previous = backup_store
        if previous is None:
            previous = {}
            for name in ('legalnoticecaption', 'legalnoticetext'):
                try:
                    previous[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    previous[name] = ''
        winreg.SetValueEx(key, 'legalnoticecaption', 0, winreg.REG_SZ, caption)
        winreg.SetValueEx(key, 'legalnoticetext', 0, winreg.REG_SZ, text)
    return previous


def sign_in_notice_check(caption):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NOTICE_KEY) as key:
            current = winreg.QueryValueEx(key, 'legalnoticecaption')[0]
    except OSError:
        current = ''
    return check(current == caption, 'shown at every Windows sign-in' if current == caption else 'not set',
                 'Run AuditraAgent.exe again as Administrator.')


def restore_sign_in_notice(previous):
    previous = previous or {'legalnoticecaption': '', 'legalnoticetext': ''}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NOTICE_KEY, 0, winreg.KEY_WRITE) as key:
            for name, value in previous.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value or '')
        return True
    except OSError:
        return False
