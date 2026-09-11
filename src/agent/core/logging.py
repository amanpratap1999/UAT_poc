"""Structured logging setup using structlog.

Provides context-bound loggers with session_id, step_index, and action
binding. Supports both human-readable console output and machine-parseable
JSON format.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog


def setup_logging(
    level: str = "INFO",
    log_format: Literal["console", "json"] = "console",
) -> None:
    """Configure structlog and stdlib logging for the application.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        log_format: Output format — 'console' for dev, 'json' for production.
    """
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=40,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging for third-party libraries
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )


def get_logger(name: str | None = None, **initial_context: object) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with optional initial context bindings.

    Args:
        name: Logger name (typically __name__ of the calling module).
        **initial_context: Key-value pairs to bind to every log entry.

    Returns:
        A bound structured logger instance.
    """
    logger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger  # type: ignore[no-any-return]
