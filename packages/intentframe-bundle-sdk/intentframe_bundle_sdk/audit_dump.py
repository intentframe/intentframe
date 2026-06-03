"""JSON-safe audit serialization for Bundle SDK context objects."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from intentframe_bundle_sdk.types import BundleAIContext, BundleContext


def audit_dump(value: Any) -> Any:
    """Recursively convert SDK / evidence values into JSON-safe audit data."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: audit_dump(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): audit_dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [audit_dump(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def dump_bundle_context(ctx: BundleContext | None) -> dict[str, Any] | None:
    """Full forensic snapshot of ``BundleContext`` for audit logs."""
    if ctx is None:
        return None
    dumped = audit_dump(ctx)
    assert isinstance(dumped, dict)
    return dumped


def dump_bundle_ai_context(ctx: BundleAIContext | None) -> dict[str, Any] | None:
    """Full forensic snapshot of ``BundleAIContext`` for audit logs."""
    if ctx is None:
        return None
    dumped = audit_dump(ctx)
    assert isinstance(dumped, dict)
    return dumped
