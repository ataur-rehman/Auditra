"""One logger for the agent: a rotating file under ProgramData, plus the console in foreground mode."""
import logging
import logging.handlers
import sys

_logger = logging.getLogger('auditra')
_logger.setLevel(logging.INFO)
_configured = False


def setup(log_dir=None, console=False):
    global _configured
    if _configured:
        return
    formatter = logging.Formatter('%(asctime)s %(message)s', '%Y-%m-%d %H:%M:%S')
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_dir / 'agent.log', maxBytes=2_000_000, backupCount=5,
                                                       encoding='utf-8')
        handler.setFormatter(formatter)
        _logger.addHandler(handler)
    if console and sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', '%H:%M:%S'))
        _logger.addHandler(stream)
    _configured = True


def log(message):
    _logger.info(message)
