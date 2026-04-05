"""Data models for the credential vault.

These are the shared types used by the vault service, client, dashboard,
and any platform component that works with credential metadata.  Secret
values are *never* part of these models — only references and metadata.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

__all__ = [
    "DeliveryMode",
    "Namespace",
    "CredentialRecord",
    "CredentialRef",
    "MaskedSummary",
    "StoreRequest",
]


# ── Namespace type ───────────────────────────────────────────────────────────

_NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@+-]*$")


def _validate_namespace(value: str) -> str:
    if "/" in value:
        raise ValueError(
            "namespace must not contain '/'; use '.' as delimiter "
            "(e.g. 'email.user@gmail.com' not 'email/user@gmail.com')"
        )
    if not _NAMESPACE_RE.match(value):
        raise ValueError(
            f"invalid namespace {value!r}; "
            "allowed: letters, digits, '.', '_', '@', '+', '-' "
            "(must start with a letter or digit)"
        )
    return value


Namespace = Annotated[str, AfterValidator(_validate_namespace)]
"""Dot-delimited logical grouping for credentials.

Examples: ``"openai"``, ``"email.user@gmail.com"``, ``"github.myorg"``.
Slashes are forbidden — use dots to separate hierarchy levels.
"""


# ── Enums ────────────────────────────────────────────────────────────────────


class DeliveryMode(StrEnum):
    """How the platform delivers a credential to a consumer.

    EXECUTOR_ONLY — fetched in-process by trusted platform services
                    (executor, EDI).  Never injected into env or
                    exposed outside the service process.

    RUNTIME_ENV  — resolved from the vault and injected into the
                   process environment of approved runtimes (e.g.
                   OPENAI_API_KEY for agent processes).
    """

    EXECUTOR_ONLY = "executor_only"
    RUNTIME_ENV = "runtime_env"


# ── Credential metadata ─────────────────────────────────────────────────────


class CredentialRecord(BaseModel):
    """Full metadata for a stored credential (value excluded).

    Persisted in the metadata SQLite DB alongside the keyring entry.
    """

    namespace: Namespace = Field(
        description='Logical grouping, e.g. "openai", "email.user@gmail.com"',
    )
    key: str = Field(
        description='Credential name within the namespace, e.g. "api_key", "password"',
    )
    delivery_mode: DeliveryMode = Field(default=DeliveryMode.EXECUTOR_ONLY)
    allowed_consumers: list[str] = Field(
        default_factory=list,
        description='Service names that may read this credential, e.g. ["executor", "edi"]',
    )
    env_name: str | None = Field(
        default=None,
        description="Environment variable name for runtime_env delivery (e.g. OPENAI_API_KEY)",
    )
    validator_id: str | None = Field(
        default=None,
        description='Optional validator to test the credential, e.g. "imap", "openai"',
    )
    masked_preview: str = Field(
        default="",
        description='Masked display string, e.g. "sk-proj-....Kx"',
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_validated_at: datetime | None = None
    last_used_at: datetime | None = None


# ── Credential reference (for adapter manifests, etc.) ───────────────────────


class CredentialRef(BaseModel):
    """Lightweight pointer to a credential in the vault.

    Used in adapter manifests and integration configs to declare
    which credential(s) a component needs at runtime.
    """

    namespace: Namespace
    key: str
    param_name: str = Field(
        description="Parameter name the consumer expects, e.g. 'api_key', 'password'",
    )


# ── Dashboard / API models ───────────────────────────────────────────────────


class MaskedSummary(BaseModel):
    """Read-only view of a credential for the dashboard.

    Contains enough metadata for UI display but never the secret value.
    """

    namespace: Namespace
    key: str
    delivery_mode: DeliveryMode
    masked_preview: str
    created_at: datetime
    updated_at: datetime
    last_validated_at: datetime | None = None
    last_used_at: datetime | None = None
    valid: bool | None = None


class StoreRequest(BaseModel):
    """Request body for storing a credential."""

    value: str = Field(description="The secret value to store")
    delivery_mode: DeliveryMode = DeliveryMode.EXECUTOR_ONLY
    allowed_consumers: list[str] = Field(default_factory=list)
    env_name: str | None = None
    validator_id: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def mask_value(value: str, *, prefix_len: int = 6, suffix_len: int = 2) -> str:
    """Return a masked representation of a secret value.

    Short values are fully masked.  Longer values show a prefix and
    suffix separated by ``....``.

    >>> mask_value("sk-proj-abc123XYZ")
    'sk-pro....YZ'
    >>> mask_value("abc")
    '****'
    """
    min_visible = prefix_len + suffix_len + 4  # 4 for the dots
    if len(value) < min_visible:
        return "****"
    return f"{value[:prefix_len]}....{value[-suffix_len:]}"
