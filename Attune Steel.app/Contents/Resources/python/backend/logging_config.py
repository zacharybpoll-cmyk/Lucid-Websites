"""Centralized logging configuration for Attune."""
import logging
import logging.handlers
import json
import os
from datetime import datetime
from pathlib import Path


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


def setup_logging(level=logging.INFO):
    """Configure attune logging with console output and rotating file handler."""
    root = logging.getLogger('attune')
    if root.handlers:
        return  # Already configured
    root.setLevel(level)

    formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s %(message)s',
        datefmt='%H:%M:%S'
    )

    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Rotating file handler (5MB per file, 3 backups)
    try:
        data_dir = Path(os.environ.get('ATTUNE_DATA_DIR', '.'))
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / 'attune.log'
        file_handler = logging.handlers.RotatingFileHandler(
            str(log_path), maxBytes=5 * 1024 * 1024, backupCount=3
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except (OSError, PermissionError):
        pass  # File logging is optional — don't block startup
