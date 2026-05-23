"""structlog setup. Pretty in dev, JSON in prod."""

from __future__ import annotations

import logging
import sys

import structlog

from .config import Settings


def configure_logging(settings: Settings) -> None:
    """Initialize structlog + stdlib logging.

    Called once on app startup from ``app.create_app``. Tests should
    call this with a Settings(env='test') instance if they need log
    capture; otherwise default handlers stay quiet enough.

    Logs go to stderr so stdout stays clean for scripts that emit JSON
    (e.g. ``python -m versawiki_api._internal.openapi > openapi.json``).
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
        force=True,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor
    if settings.log_json or settings.env in {"staging", "prod"}:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience wrapper so callers don't import structlog directly."""
    return structlog.get_logger(name) if name else structlog.get_logger()
