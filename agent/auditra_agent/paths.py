"""Where the agent keeps its files, and the agent's own configuration (server URL and token).

    C:\\ProgramData\\Auditra\\config.json   server, token, agent id, owner (written by the installer)
    C:\\ProgramData\\Auditra\\outbox.db     events waiting to be sent, bookmarks, cached server config
    C:\\ProgramData\\Auditra\\logs\\         agent.log (rotating)

The folder is readable only by SYSTEM and Administrators, so an employee cannot copy the token and send events in
the laptop's name. AUDITRA_HOME moves it (development and tests).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get('AUDITRA_HOME') or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'Auditra')
CONFIG = DATA_DIR / 'config.json'
OUTBOX = DATA_DIR / 'outbox.db'
LOG_DIR = DATA_DIR / 'logs'
INSTALL_DIR = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Auditra'
INSTALLED_EXE = INSTALL_DIR / 'AuditraAgent.exe'
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def frozen():
    return bool(getattr(sys, 'frozen', False))


def bundled(name):
    """A file shipped inside the exe (PyInstaller) or next to the package (development)."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / name


def build_defaults():
    """Values baked in at build time (agent/build.ps1 -Server ...)."""
    try:
        return json.loads(bundled('defaults.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def load_config():
    config = {}
    try:
        config = json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    # Development overrides.
    if os.environ.get('AUDITRA_SERVER'):
        config['server'] = os.environ['AUDITRA_SERVER']
    if os.environ.get('AUDITRA_ENROLMENT_KEY'):
        config['enrolment_key'] = os.environ['AUDITRA_ENROLMENT_KEY']
    config['server'] = (config.get('server') or build_defaults().get('server') or 'http://127.0.0.1:8000').rstrip('/')
    return config


def save_config(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(config, indent=1), encoding='utf-8')
    os.replace(tmp, CONFIG)


def secure_data_dir():
    """SYSTEM and Administrators only (SIDs, so it works in every Windows language)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ['icacls', str(DATA_DIR), '/inheritance:r', '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    ).returncode == 0
