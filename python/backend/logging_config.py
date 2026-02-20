"""Centralized logging configuration for Attune."""
import logging
import json
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


def setup_logging(level=logging.INFO):
    """Configure attune logging with console output."""
    root = logging.getLogger('attune')
    if root.handlers:
        return  # Already configured
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s %(message)s',
        datefmt='%H:%M:%S'
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
