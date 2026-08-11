"""Structured logging setup.

One configuration point for the whole process. Application code never calls
`print()` — it calls `structlog.get_logger(__name__)` and logs at the level whose
meaning matches the event:

    debug   intermediate values, SQL text, cache hits
    info    request start/end with timing, successful business events
    warn    recoverable problems, retries, degraded fallbacks
    error   unhandled exceptions and failed requests, with the traceback attached
"""

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings

REDACTED_PLACEHOLDER = "***"
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "monid_api_key",
        "secret",
        "cookie",
        "set-cookie",
    }
)


def _redact_sensitive_fields(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Drop secrets before anything reaches a sink — including at debug level."""
    for field_name in list(event_dict):
        if field_name.lower() in SENSITIVE_FIELD_NAMES:
            event_dict[field_name] = REDACTED_PLACEHOLDER
    return event_dict


def _build_shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive_fields,
    ]


def configure_logging(settings: Settings) -> None:
    """Wire structlog and the stdlib logger to a single, level-configurable pipeline."""
    log_level = getattr(logging, settings.log_level.upper())

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*_build_shared_processors(), renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        # The stdlib factory (not PrintLogger) so `add_logger_name` has a name to read
        # and library logs share the same handlers.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    for noisy_logger_name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy_logger_name).handlers.clear()
        logging.getLogger(noisy_logger_name).propagate = True
