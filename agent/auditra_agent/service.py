"""The Windows service (LocalSystem, automatic start, restarts itself on failure)."""
import subprocess
import sys
import threading

import servicemanager
import win32service
import win32serviceutil

from . import SERVICE_NAME, VERSION
from .log import log, setup
from .paths import INSTALLED_EXE, LOG_DIR, NO_WINDOW

DISPLAY_NAME = 'Auditra Agent'
DESCRIPTION = ('Records sign-ins, access to company personal-data folders, USB storage, printing and visits to '
               'file-sharing sites for GDPR compliance monitoring. File contents are never read.')


class AuditraService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = DISPLAY_NAME
    _svc_description_ = DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()

    def SvcDoRun(self):
        setup(LOG_DIR)
        servicemanager.LogInfoMsg(f'{DISPLAY_NAME} {VERSION} starting')
        from .runner import Agent
        try:
            Agent().run(self.stop_event)
        except Exception as exc:
            log(f'service stopped on error: {exc}')
            raise


def dispatch():
    """Entry point when the Service Control Manager starts ``AuditraAgent.exe service``."""
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(AuditraService)
    servicemanager.StartServiceCtrlDispatcher()


def installed():
    try:
        win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        return True
    except Exception:
        return False


def running():
    try:
        return win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1] == win32service.SERVICE_RUNNING
    except Exception:
        return False


def install(exe=INSTALLED_EXE):
    if installed():
        stop()
        win32serviceutil.ChangeServiceConfig(
            f'{__name__}.AuditraService', SERVICE_NAME, startType=win32service.SERVICE_AUTO_START,
            exeName=str(exe), exeArgs='service', displayName=DISPLAY_NAME, description=DESCRIPTION)
    else:
        win32serviceutil.InstallService(
            f'{__name__}.AuditraService', SERVICE_NAME, DISPLAY_NAME, startType=win32service.SERVICE_AUTO_START,
            exeName=str(exe), exeArgs='service', description=DESCRIPTION)
    # Restart after 5 s, 5 s, then 30 s if the process ever dies; reset the count after a day.
    subprocess.run(['sc', 'failure', SERVICE_NAME, 'reset=', '86400', 'actions=',
                    'restart/5000/restart/5000/restart/30000'], capture_output=True, creationflags=NO_WINDOW)
    subprocess.run(['sc', 'failureflag', SERVICE_NAME, '1'], capture_output=True, creationflags=NO_WINDOW)


def start():
    win32serviceutil.StartService(SERVICE_NAME)
    win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_RUNNING, 60)


def stop():
    if running():
        win32serviceutil.StopService(SERVICE_NAME)
        try:
            win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_STOPPED, 30)
        except Exception:
            pass


def remove():
    if installed():
        stop()
        win32serviceutil.RemoveService(SERVICE_NAME)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(AuditraService, argv=sys.argv)
