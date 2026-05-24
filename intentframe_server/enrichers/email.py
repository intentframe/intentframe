"""Backward-compatible re-export — implementation lives in action bundle."""

from intentframe_native_bundles.actions.email.enrich import (
    EMAIL_MESSAGE_ACTIONS,
    close,
    enrich_intent,
)

__all__ = [
    "EMAIL_MESSAGE_ACTIONS",
    "close",
    "enrich_intent",
]
