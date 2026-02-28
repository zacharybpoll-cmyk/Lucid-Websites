"""Centralized logging configuration for Attune."""
import logging
import logging.handlers
import json
import os
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter."""
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(level=logging.INFO, log_dir=None):
    """Configure attune logging with console output and optional file logging.

    Args:
        level: Console log level (default INFO).
        log_dir: If provided, also write DEBUG-level logs to attune.log
                 in this directory (RotatingFileHandler, 5MB, 3 backups).
    """
    root = logging.getLogger('attune')
    if root.handlers:
        return  # Already configured
    root.setLevel(logging.DEBUG)  # Root at DEBUG; handlers filter their own level

    # Console handler (INFO level)
    console = logging.StreamHandler()
    console.setLevel(level)
    console_fmt = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s %(message)s',
        datefmt='%H:%M:%S'
    )
    console.setFormatter(console_fmt)
    root.addHandler(console)

    # File handler (DEBUG level) — captures VAD diagnostics, pipeline details
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'attune.log')
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_fmt)
        root.addHandler(file_handler)
