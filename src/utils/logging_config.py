"""
Logging configuration for the application.

This module sets up structured logging based on configuration settings.
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.settings_db import get_settings


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        # Add any extra fields passed to the logger
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "request_id",
            ]:
                log_data[key] = value

        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging(settings=None) -> None:
    """
    Set up application logging based on configuration.

    Args:
        settings: Optional settings object (will use get_settings() if not provided)
    """
    if settings is None:
        settings = get_settings()

    log_config = settings.logging

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_config.level))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_config.level))

    # Set formatter based on settings
    if log_config.format == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Add file handler if log file is specified
    if log_config.log_file:
        log_file_path = Path(log_config.log_file)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Use rotating file handler to prevent unbounded growth
        max_bytes = log_config.max_file_size_mb * 1024 * 1024
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=max_bytes,
            backupCount=log_config.backup_count,
        )
        file_handler.setLevel(getattr(logging, log_config.level))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Set specific loggers to appropriate levels
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("databricks").setLevel(logging.INFO)

    root_logger.info(
        "Logging configured",
        extra={
            "level": log_config.level,
            "format": log_config.format,
            "log_file": log_config.log_file,
        },
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class RequestIDFilter(logging.Filter):
    """
    Filter that adds request_id to log records.

    This is useful for tracing logs across a single request.
    """

    def __init__(self, request_id: str):
        """
        Initialize filter with request ID.

        Args:
            request_id: Unique request identifier
        """
        super().__init__()
        self.request_id = request_id

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add request_id to log record.

        Args:
            record: Log record to modify

        Returns:
            Always True (don't filter any records)
        """
        record.request_id = self.request_id
        return True


def add_request_id_to_logger(logger: logging.Logger, request_id: str) -> None:
    """
    Add a request ID filter to a logger.

    Args:
        logger: Logger to modify
        request_id: Request ID to add to all log records
    """
    request_filter = RequestIDFilter(request_id)
    logger.addFilter(request_filter)


def remove_request_id_from_logger(logger: logging.Logger) -> None:
    """
    Remove all RequestIDFilter instances from a logger.

    Args:
        logger: Logger to modify
    """
    logger.filters = [
        f for f in logger.filters if not isinstance(f, RequestIDFilter)
    ]

