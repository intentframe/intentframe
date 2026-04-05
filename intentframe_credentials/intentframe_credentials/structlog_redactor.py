"""structlog processor that scrubs sensitive keys from log events.

Drop this into any ``structlog.configure(processors=[...])`` pipeline
to prevent credential leakage through logs, regardless of which module
emits the event.

Usage::

    import structlog
    from intentframe_credentials.structlog_redactor import redact_credentials

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_credentials,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )
"""

from __future__ import annotations

from typing import Any

from intentframe_credentials.redaction import REDACTED_VALUE, SENSITIVE_KEYS

__all__ = ["redact_credentials"]


def redact_credentials(
    _logger: Any,
    _method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor: replace values of sensitive keys with ``[REDACTED]``."""
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED_VALUE
    return event_dict
