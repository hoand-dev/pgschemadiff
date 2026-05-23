"""Structured logging configuration.

Uses ``structlog`` with two renderers:
- JSON (production / CI / file output)
- Console with color (interactive CLI / TUI)

Selected via the ``PGSD_LOG_FORMAT`` env var (``json`` | ``console``, default ``console``).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Any, cast

import structlog

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger
    from structlog.types import EventDict, Processor


def _drop_color_message_key(_: object, __: str, event_dict: EventDict) -> EventDict:
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(level: str = "INFO", *, fmt: str | None = None) -> None:
    """Configure the global ``structlog`` and ``logging`` pipelines.

    Safe to call multiple times; later calls reconfigure.
    """
    fmt = fmt or os.environ.get("PGSD_LOG_FORMAT", "console")
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _drop_color_message_key,
    ]

    final_processor: Processor
    if fmt == "json":
        final_processor = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            final_processor,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )


def get_logger(name: str | None = None, **initial_values: Any) -> BoundLogger:
    """Get a logger bound to the given name and initial context values."""
    logger = structlog.get_logger(name)
    if initial_values:
        logger = logger.bind(**initial_values)
    return cast("BoundLogger", logger)
