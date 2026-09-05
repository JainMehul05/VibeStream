"""Structured logging configuration and JSON formatter."""

import json
import logging
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON log formatter with standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process",
                "processName", "relativeCreated", "thread", "threadName",
                "exc_info", "exc_text", "stack_info", "getMessage"
            }:
                # Only include JSON-serializable values
                try:
                    json.dumps(value)
                    log_obj[key] = value
                except (TypeError, ValueError):
                    log_obj[key] = str(value)

        # Include exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """Get a structured logger instance."""
    return logging.getLogger(name)