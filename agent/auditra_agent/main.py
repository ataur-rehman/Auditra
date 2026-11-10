"""AuditraAgent.exe command line.

    AuditraAgent.exe              install (double-click): UAC prompt, enrolment code, background agent
    AuditraAgent.exe uninstall    remove the agent and undo the Windows changes
    AuditraAgent.exe run          run in this window with every event printed (rehearsals, development)
    AuditraAgent.exe stop         stop the background agent (for a rehearsal in a window)
    AuditraAgent.exe start        start the background agent again
    AuditraAgent.exe status       state, server, events waiting, and the end of the agent's log
    AuditraAgent.exe agent        the background agent itself (started by Task Scheduler as SYSTEM)

Development without building the exe (from the agent folder, in an Administrator PowerShell):

    $env:AUDITRA_SERVER = "http://127.0.0.1:8000"
    $env:AUDITRA_ENROLMENT_KEY = "auditra-ingest-dev-key"   # LAN demo only; otherwise enrol with a code
    python -m auditra_agent run
"""
import ctypes
import faulthandler
import sys
import threading


def attach_console():
    """The exe is built without a console window (double-click shows only the setup window). Commands that print
    open one, or reuse the PowerShell window they were started from."""
    # Always a window of its own: PowerShell does not wait for a windowless exe, so sharing its console would mix
    # the agent's lines with the prompt.
    kernel32 = ctypes.windll.kernel32
    kernel32.AllocConsole()
    kernel32.SetConsoleTitleW('Auditra Agent')
    sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
    sys.stderr = sys.stdout


def _crash_log():
    """A native crash (not a Python exception) still leaves a traceback in logs\\crash.log."""
    from .paths import LOG_DIR

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOG_DIR / 'crash.log', 'a', encoding='utf-8')
    faulthandler.enable(handle)
    return handle


def run_agent(console):
    from .log import log, setup
    from .paths import LOG_DIR
    from .runner import Agent
    from .task import SingleInstance

    setup(LOG_DIR, console=console)
    crash = _crash_log()
    instance = SingleInstance()
    if not instance.acquired:
        message = ('Another Auditra agent is already running on this PC. Stop the background agent first: '
                   'AuditraAgent.exe stop')
        log(message) if not console else print(message)
        return
    stop = threading.Event()
    try:
        Agent(verbose=console).run(stop)
    except KeyboardInterrupt:
        stop.set()
        print('\nAgent stopped.')
    finally:
        crash.close()


def status_text():
    from . import task
    from .outbox import Outbox
    from .paths import CONFIG, LOG_DIR, OUTBOX, load_config

    try:
        config = load_config() if CONFIG.exists() else {}
    except PermissionError:
        return 'Run this from a PowerShell opened with "Run as administrator": the agent folder is locked to admins.'
    state = 'running' if task.running() else 'installed, not running' if task.installed() else 'not installed'
    out = [f'Agent     : {state}', f'Server    : {config.get("server", "-")}',
           f'Enrolled  : {config.get("employee") or ("yes" if config.get("token") else "no")}']
    if OUTBOX.exists():
        outbox = Outbox(OUTBOX)
        out.append(f'Waiting   : {outbox.pending()} event(s) not yet sent')
        outbox.close()
    for name, count in (('agent.log', 12), ('crash.log', 20)):
        path = LOG_DIR / name
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()[-count:]
        except OSError:
            continue
        if lines:
            out += ['', f'--- {path} (last {len(lines)} lines) ---', *lines]
    return '\n'.join(out)


def status():
    text = status_text()
    if getattr(sys, 'frozen', False):
        # The exe has no console of its own and PowerShell does not wait for it, so show a window instead
        # (Ctrl+C in the window copies its text).
        ctypes.windll.user32.MessageBoxW(None, text, 'Auditra Agent status', 0x40)
    else:
        print(text)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0].lower() if args else 'install'
    if command in ('agent', 'service'):  # 'service' kept for agents installed by an earlier build
        run_agent(console=False)
        return
    if command in ('install', 'setup'):
        from .installer import run_install
        run_install()
        return
    if command in ('uninstall', 'remove'):
        from .installer import run_uninstall
        run_uninstall()
        return
    if command == 'status':
        status()
        return
    if command in ('stop', 'start'):
        from . import task
        ok = task.stop() if command == 'stop' else task.start()
        text = (f'Background agent {"stopped" if command == "stop" else "started"}.' if ok is not False else
                'Task Scheduler refused. Run this from a PowerShell opened with "Run as administrator".')
        if getattr(sys, 'frozen', False):
            ctypes.windll.user32.MessageBoxW(None, text, 'Auditra Agent', 0x40)
        else:
            print(text)
        return
    if getattr(sys, 'frozen', False):
        attach_console()
    if command == 'run':
        run_agent(console=True)
    else:
        print(__doc__)
        input('Press Enter to close.')


if __name__ == '__main__':
    main()
