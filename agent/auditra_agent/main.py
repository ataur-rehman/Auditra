"""AuditraAgent.exe command line.

    AuditraAgent.exe              install (double-click): UAC prompt, enrolment code, service
    AuditraAgent.exe uninstall    remove the service and undo the Windows changes
    AuditraAgent.exe run          run in this window with every event printed (rehearsals, development)
    AuditraAgent.exe status       service state, Windows checks, events waiting to be sent
    AuditraAgent.exe service      used by Windows to start the service

Development without building the exe (from the agent folder, in an Administrator PowerShell):

    $env:AUDITRA_SERVER = "http://127.0.0.1:8000"
    $env:AUDITRA_ENROLMENT_KEY = "auditra-ingest-dev-key"   # LAN demo only; otherwise enrol with a code
    python -m auditra_agent run
"""
import ctypes
import sys
import threading


def attach_console():
    """The exe is built without a console window (double-click shows only the setup window). Commands that print
    open one, or reuse the PowerShell window they were started from."""
    kernel32 = ctypes.windll.kernel32
    if not kernel32.AttachConsole(-1):
        kernel32.AllocConsole()
    sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
    sys.stderr = sys.stdout


def run_foreground():
    from .log import setup
    from .paths import LOG_DIR
    from .runner import Agent

    setup(LOG_DIR, console=True)
    stop = threading.Event()
    agent = Agent(verbose=True)
    try:
        agent.run(stop)
    except KeyboardInterrupt:
        stop.set()
        print('\nAgent stopped.')


def status():
    from . import service
    from .outbox import Outbox
    from .paths import CONFIG, OUTBOX, load_config

    config = load_config() if CONFIG.exists() else {}
    print(f'Service   : {"running" if service.running() else "installed, stopped" if service.installed() else "not installed"}')
    print(f'Server    : {config.get("server", "-")}')
    print(f'Enrolled  : {config.get("employee") or ("yes" if config.get("token") else "no")}')
    if OUTBOX.exists():
        outbox = Outbox(OUTBOX)
        print(f'Waiting   : {outbox.pending()} event(s) not yet sent')
        outbox.close()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0].lower() if args else 'install'
    if command == 'service':
        from .service import dispatch
        dispatch()
        return
    if command in ('install', 'setup'):
        from .installer import run_install
        run_install()
        return
    if command in ('uninstall', 'remove'):
        from .installer import run_uninstall
        run_uninstall()
        return
    if getattr(sys, 'frozen', False):
        attach_console()
    if command == 'run':
        run_foreground()
    elif command == 'status':
        status()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
