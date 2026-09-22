"""Logging setup with a redaction filter so credentials never reach the logs."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import settings

#: Patterns for values that must never be written to a log record.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|x-api-key|bearer)\s*[:=]\s*\S+"),
)

REDACTED = "***REDACTED***"


def redact(text: str) -> str:
    """Strip anything that looks like a credential out of ``text``."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    """Applies :func:`redact` to every formatted log message."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_value(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_value(v) for v in record.args)
        return True


def _redact_value(value: Any) -> Any:
    return redact(value) if isinstance(value, str) else value


def configure_logging() -> None:
    """Install the root logging configuration for the application."""
    level = logging.DEBUG if settings.debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s :: %(message)s"))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn's own handlers would bypass the redaction filter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False

    # Alembic announces each internal plugin at INFO when it is imported, i.e.
    # on every startup. Keep its "Running upgrade ..." lines, drop that noise.
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
