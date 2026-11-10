"""Install and uninstall: what happens when an employee double-clicks AuditraAgent.exe.

1. Windows asks for administrator approval (UAC). Reading the Security log and switching on auditing need it, so
   a standard employee account is asked for an administrator's password: that is the permission step.
2. A small window asks for the enrolment code from the Auditra console (server address pre-filled).
3. The code is checked with the server first. A wrong or expired code stops here and nothing is changed.
4. The agent is copied to Program Files, its folder in ProgramData is locked to SYSTEM and Administrators,
   Windows auditing is switched on and the sign-in notice is set.
5. The agent is registered in Task Scheduler (runs as SYSTEM at boot, restarted if it stops) and started.

Uninstall reverses every step and puts back the audit policy that was there before.
"""
import ctypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import winreg

import requests

from . import SERVICE_NAME, VERSION, task, winconfig
from .collectors import console_account, is_admin
from .log import log, setup
from .outbox import Outbox
from .paths import (
    CONFIG, DATA_DIR, INSTALL_DIR, INSTALLED_EXE, LOG_DIR, NO_WINDOW, OUTBOX, build_defaults, frozen, load_config,
    save_config, secure_data_dir,
)

UNINSTALL_KEY = rf'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{SERVICE_NAME}'


def relaunch_elevated(args):
    """Ask Windows for administrator approval (the UAC prompt) and run again with ``args``."""
    if frozen():
        exe, params = sys.executable, ' '.join(args)
    else:
        exe, params = sys.executable, ' '.join(['-m', 'auditra_agent', *args])
    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', exe, params, os.getcwd(), 1)
    return result > 32  # <= 32 means the person declined or it failed


def message(text, title='Auditra Agent', error=False):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)


# ------------------------------------------------------------------ the steps
def enrol(server, code):
    response = requests.post(f'{server.rstrip("/")}/api/agent/enrol/', json={
        'code': code.strip(), 'hostname': socket.gethostname(), 'console_user': console_account(),
        'version': VERSION, 'is_admin': True,
    }, timeout=30)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200:
        raise RuntimeError(data.get('error') or f'The server answered {response.status_code}.')
    return data


def copy_self(seconds=20):
    """Copy this exe to Program Files. The old agent may take a moment to exit, so keep closing it and retrying."""
    if not frozen():
        return None  # development: the background task needs the built exe
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(str(INSTALLED_EXE)):
        return INSTALLED_EXE
    deadline = time.monotonic() + seconds
    while True:
        try:
            shutil.copy2(sys.executable, INSTALLED_EXE)
            return INSTALLED_EXE
        except OSError:
            if time.monotonic() > deadline:
                raise
            stop_previous()
            time.sleep(1)


def add_to_apps_list():
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0, winreg.KEY_WRITE) as key:
        for name, value in {
            'DisplayName': 'Auditra Agent', 'DisplayVersion': VERSION, 'Publisher': 'Auditra',
            'UninstallString': f'"{INSTALLED_EXE}" uninstall', 'DisplayIcon': str(INSTALLED_EXE),
            'InstallLocation': str(INSTALL_DIR),
        }.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'NoRepair', 0, winreg.REG_DWORD, 1)


def install(server, code, say):
    say('Checking the enrolment code with the server ...')
    data = enrol(server, code)
    say(f'Enrolled for {data["employee"]}.')
    linked = data.get('linked') or {}
    if linked.get('error'):
        say(f'Note: {linked["error"]}')
    elif linked.get('account'):
        say(f'Windows account {linked["account"]} linked to {data["employee"]}.')

    # The code is used now and the server issued a new token, so save it before anything else can fail; if a later
    # step fails, the agent that was already installed restarts with the new token instead of being locked out.
    say('Locking the agent folder to SYSTEM and Administrators ...')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secure_data_dir()
    save_config({'server': server.rstrip('/'), 'token': data['token'], 'agent_id': data['agent_id'],
                 'employee': data['employee']})
    try:
        return _install_steps(data, say)
    except Exception:
        if task.installed():
            task.start()
            say('The agent that was already installed was restarted with the new enrolment.')
        raise


def _install_steps(data, say):
    say('Stopping a previous agent, if any ...')
    stop_previous()
    exe = copy_self()

    outbox = Outbox(OUTBOX)
    outbox.put('server_config', data['config'])

    say('Switching on Windows auditing ...')
    winconfig.backup_audit_policy()
    checks = {'audit_policy': winconfig.AuditPolicy().ensure(data['config'].get('required_audit', {})),
              'print_log': winconfig.ensure_print_log(),
              'security_log_size': winconfig.ensure_security_log_size()}
    result, added = winconfig.ensure_file_auditing(data['config'].get('catalogue_paths', []),
                                                   outbox.get('sacl_added', []))
    outbox.put('sacl_added', added)
    checks['file_auditing'] = result
    notice = data['config'].get('notice') or {}
    if notice.get('caption'):
        previous = winconfig.set_sign_in_notice(notice['caption'], notice['text'], outbox.get('notice_backup'))
        if outbox.get('notice_backup') is None:
            outbox.put('notice_backup', previous)
        checks['sign_in_notice'] = winconfig.sign_in_notice_check(notice['caption'])
    outbox.close()
    for name, item in checks.items():
        say(f'  {"OK " if item["ok"] else "!! "} {name.replace("_", " ")}: {item["detail"]}')

    if exe is None:
        say('Development run: start the agent with  python -m auditra_agent run')
        return checks
    say('Registering the background agent (Task Scheduler, runs as SYSTEM, starts with Windows) ...')
    task.install(exe)
    add_to_apps_list()
    task.start()
    if wait_until_running():
        say('The Auditra agent is running in the background and starts with Windows.')
    else:
        say('!!  The agent did not stay running. Run  AuditraAgent.exe status  in an Administrator '
            'PowerShell and send the output to the administrator.')
        checks['agent_running'] = winconfig.check(False, 'did not stay running')
    return checks


def stop_previous():
    """Stop the background agent and any copy still running from Program Files, so the exe can be replaced."""
    task.stop()
    task.remove_legacy_service()
    # Task Scheduler's End stops only the one-file launcher; its child (the agent itself, the same exe) keeps
    # running and keeps the file open. WMI sees SYSTEM's processes with their paths; this process and its own
    # launcher are left alone (they run the exe being installed, or are the uninstaller).
    script = (
        f"$me = {os.getpid()}; "
        "$parent = (Get-CimInstance Win32_Process -Filter \"ProcessId=$me\").ParentProcessId; "
        "Get-CimInstance Win32_Process -Filter \"Name='AuditraAgent.exe'\" | "
        f"Where-Object {{ $_.ProcessId -ne $me -and $_.ProcessId -ne $parent -and $_.ExecutablePath -eq '{INSTALLED_EXE}' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, creationflags=NO_WINDOW)
    # The background agent always runs as SYSTEM and the installer never does, so this cannot stop the installer.
    subprocess.run(['taskkill', '/F', '/IM', 'AuditraAgent.exe', '/FI', r'USERNAME eq NT AUTHORITY\SYSTEM'],
                   capture_output=True, creationflags=NO_WINDOW)


def wait_until_running(seconds=20):
    """True if the agent starts and is still running a few seconds later (a crash on start shows here)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not task.running():
        time.sleep(1)
    if not task.running():
        return False
    time.sleep(6)
    return task.running()


def uninstall(say):
    say('Stopping and removing the background agent ...')
    task.remove()
    stop_previous()
    if OUTBOX.exists():
        outbox = Outbox(OUTBOX)
        removed = [p for p in outbox.get('sacl_added', []) if winconfig.remove_sacl(p)]
        say(f'File auditing removed from {len(removed)} folder(s).')
        winconfig.restore_sign_in_notice(outbox.get('notice_backup'))
        say('Sign-in notice removed.')
        outbox.close()
    ok, detail = winconfig.restore_audit_policy()
    say('Audit policy restored.' if ok else f'Audit policy not restored ({detail}).')
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    if frozen() and INSTALL_DIR.exists():
        # The running exe cannot delete itself; a short-lived cmd removes the folder once this process exits.
        subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{INSTALL_DIR}"',
                         creationflags=NO_WINDOW, shell=False)
    say('Auditra Agent removed.')


# ------------------------------------------------------------------ the window
def install_window():
    import tkinter as tk
    from tkinter import ttk

    defaults = build_defaults()
    current = load_config() if CONFIG.exists() else {}
    root = tk.Tk()
    root.title('Auditra Agent setup')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.grid()
    ttk.Label(frame, text='Auditra Agent', font=('Segoe UI', 13, 'bold')).grid(column=0, row=0, columnspan=2,
                                                                              sticky='w')
    ttk.Label(frame, wraplength=440, justify='left', text=(
        'This laptop will be monitored for the protection of personal data (GDPR Art. 32). Auditra records '
        'sign-ins, access to the company folders that hold personal data, USB storage, printing and visits to '
        'file-sharing sites. It never reads file contents, keystrokes or screens.\n\n'
        'Get the enrolment code from the Auditra console: sign in, read the monitoring notice, then choose '
        '"Get enrolment code".')).grid(column=0, row=1, columnspan=2, sticky='w', pady=(4, 12))
    ttk.Label(frame, text='Server').grid(column=0, row=2, sticky='w')
    # The address built into this exe wins: a new build for a new server must not inherit an older install's.
    server_var = tk.StringVar(value=defaults.get('server') or current.get('server') or 'http://127.0.0.1:8000')
    ttk.Entry(frame, textvariable=server_var, width=46).grid(column=1, row=2, sticky='w', pady=2)
    ttk.Label(frame, text='Enrolment code').grid(column=0, row=3, sticky='w')
    code_var = tk.StringVar()
    code_entry = ttk.Entry(frame, textvariable=code_var, width=20, font=('Consolas', 12))
    code_entry.grid(column=1, row=3, sticky='w', pady=2)
    output = tk.Text(frame, width=64, height=12, font=('Consolas', 9), state='disabled')
    output.grid(column=0, row=5, columnspan=2, pady=(12, 0))
    button = ttk.Button(frame, text='Install and start monitoring')
    button.grid(column=0, row=4, columnspan=2, sticky='e', pady=(10, 0))

    def say(line):
        log(line)

        def add():
            output.configure(state='normal')
            output.insert('end', line + '\n')
            output.see('end')
            output.configure(state='disabled')
        root.after(0, add)

    def work():
        try:
            checks = install(server_var.get().strip(), code_var.get().strip(), say)
            failing = [k for k, v in checks.items() if not v['ok']]
            say('')
            say('Monitoring is active. You can close this window.' if not failing else
                'Monitoring is active, but some Windows settings need attention (see above). '
                'They are also shown to the administrator in Agents & Health.')
            root.after(0, lambda: button.configure(text='Close', state='normal', command=root.destroy))
        except Exception as exc:
            say(f'Not installed: {exc}')
            root.after(0, lambda: button.configure(state='normal'))

    def start():
        if not code_var.get().strip():
            say('Type the enrolment code first.')
            return
        button.configure(state='disabled')
        threading.Thread(target=work, daemon=True).start()

    button.configure(command=start)
    code_entry.focus()
    root.mainloop()


def run_install():
    if not is_admin():
        if not relaunch_elevated(['install']):
            message('Auditra needs administrator approval to switch on Windows auditing. '
                    'Ask your IT administrator to approve the installation.', error=True)
        return
    setup(LOG_DIR)
    install_window()


def run_uninstall():
    if not is_admin():
        if not relaunch_elevated(['uninstall']):
            message('Removing Auditra needs administrator approval.', error=True)
        return
    setup(LOG_DIR, console=True)
    lines = []
    try:
        uninstall(lambda line: (log(line), lines.append(line)))
    except Exception as exc:
        lines.append(f'Error: {exc}')
    message('\n'.join(lines))
