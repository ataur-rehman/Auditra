"""Runs the agent in the background as SYSTEM through Task Scheduler.

Why not a classic Windows service: a PyInstaller one-file exe starts a child process, so the process the Service
Control Manager launched is not the one that talks to it; hosted that way the agent crashed on start. Task
Scheduler runs the exact code path of ``AuditraAgent.exe run`` (no console), which is tested, and gives the same
guarantees:

  * starts at boot, before anyone signs in, as SYSTEM with the highest privileges;
  * restarted every minute if it ever exits with an error, and re-checked every 5 minutes;
  * one copy at a time: Task Scheduler ignores a new start while one runs, and a named mutex stops a second copy
    started any other way (for example ``run`` in a window while the background agent is running).
"""
import subprocess
from datetime import datetime
from xml.sax.saxutils import escape

import pywintypes
import win32api
import win32event

from .paths import DATA_DIR, INSTALLED_EXE, NO_WINDOW

TASK_NAME = r'\Auditra\AuditraAgent'
MUTEX_NAME = 'Global\\AuditraAgent'
LEGACY_SERVICE = 'AuditraAgent'
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>Auditra</Author>
    <Description>Auditra Agent: records sign-ins, access to company personal-data folders, USB storage, printing and visits to file-sharing sites for GDPR compliance monitoring. File contents are never read.</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
    <TimeTrigger>
      <Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>6</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="System">
    <Exec><Command>"{exe}"</Command><Arguments>agent</Arguments></Exec>
  </Actions>
</Task>
"""


def _schtasks(*args):
    result = subprocess.run(['schtasks', *args], capture_output=True, text=True, creationflags=NO_WINDOW)
    return result.returncode, (result.stdout or '') + (result.stderr or '')


# ------------------------------------------------------------------ one copy at a time
class SingleInstance:
    """Holds the agent's named mutex. ``acquired`` is False when another copy already runs."""

    def __init__(self):
        self.handle = None
        self.acquired = False
        if running():
            return
        try:
            self.handle = win32event.CreateMutex(None, False, MUTEX_NAME)
            self.acquired = win32api.GetLastError() != ERROR_ALREADY_EXISTS
        except pywintypes.error as exc:
            # A standard (development) account may not create Global objects; it cannot run beside SYSTEM's
            # agent anyway, because running() above already found no other copy.
            self.acquired = exc.winerror == ERROR_ACCESS_DENIED


def running():
    """True when an agent (the background task or a window) is running on this PC."""
    try:
        handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, MUTEX_NAME)
        handle.Close()
        return True
    except pywintypes.error as exc:
        return exc.winerror == ERROR_ACCESS_DENIED  # exists, owned by SYSTEM


# ------------------------------------------------------------------ the scheduled task
def installed():
    return _schtasks('/Query', '/TN', TASK_NAME)[0] == 0


def install(exe=INSTALLED_EXE):
    remove_legacy_service()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    xml_path = DATA_DIR / 'task.xml'
    start = datetime.now().replace(microsecond=0).isoformat()
    xml_path.write_text(TASK_XML.format(exe=escape(str(exe)), start=start), encoding='utf-16')
    code, output = _schtasks('/Create', '/TN', TASK_NAME, '/XML', str(xml_path), '/F')
    if code != 0:
        raise RuntimeError(f'Task Scheduler refused the Auditra task: {output.strip()[:300]}')


def start():
    return _schtasks('/Run', '/TN', TASK_NAME)[0] == 0


def stop():
    if installed():
        return _schtasks('/End', '/TN', TASK_NAME)[0] == 0
    return False


def remove():
    if installed():
        stop()
        _schtasks('/Delete', '/TN', TASK_NAME, '/F')
    remove_legacy_service()


def remove_legacy_service():
    """Agent 3.0 builds before this change installed a Windows service; remove it if it is there."""
    query = subprocess.run(['sc', 'query', LEGACY_SERVICE], capture_output=True, creationflags=NO_WINDOW)
    if query.returncode == 0:
        subprocess.run(['sc', 'stop', LEGACY_SERVICE], capture_output=True, creationflags=NO_WINDOW)
        subprocess.run(['sc', 'delete', LEGACY_SERVICE], capture_output=True, creationflags=NO_WINDOW)
