"""
Pydantic models for the IntentFrame Executor.

These models define every data shape that crosses a boundary in the system.
All inter-module communication uses these models -- no raw dicts at boundaries.

Layout:
    - Enums: status types, security event types
    - Protocol boundary: ExecutionRequest, ExecutionResult, AuthorizationProof
    - Auth: AuthResult
    - Audit & security: AuditEntry, SecurityEvent, RollbackEntry
    - Adapter: AdapterManifest
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════════


class ExecutionStatus(str, Enum):
    """Lifecycle status of a single execution."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ROLLED_BACK = "ROLLED_BACK"


class RollbackStatus(str, Enum):
    """Status of a stored rollback capability."""

    AVAILABLE = "AVAILABLE"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class SecurityEventType(str, Enum):
    """Categories of security-relevant events."""

    INVALID_AUTH = "INVALID_AUTH"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    ADAPTER_CRASH = "ADAPTER_CRASH"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    SUSPICIOUS_PATTERN = "SUSPICIOUS_PATTERN"


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _utc_now() -> str:
    """ISO 8601 timestamp in UTC. Single source of truth for all timestamps."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """UUID4 string. Single source of truth for all ID generation."""
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════════════════
# Protocol Boundary Models (what crosses the wire)
# ═══════════════════════════════════════════════════════════════════════════════


class AuthorizationProof(BaseModel):
    """Authorization proof attached to every execution request.

    The executor does not know WHO authorized the request -- only
    that the proof is valid according to the configured AuthVerifier.

    Attributes:
        scheme: Auth scheme identifier (e.g., "guardian_hmac", "mtls", "bearer").
        token: The actual auth token, HMAC signature, or certificate reference.
        timestamp: When the proof was issued (ISO 8601 UTC).
        metadata: Scheme-specific extra data (e.g., key ID for HMAC rotation).
    """

    model_config = ConfigDict(frozen=True)

    scheme: str = Field(
        ..., description="Auth scheme: guardian_hmac, mtls, bearer, etc."
    )
    token: str = Field(
        ..., description="The auth token, signature, or certificate reference"
    )
    timestamp: str = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Scheme-specific extra data"
    )


class RequestMetadata(BaseModel):
    """Origin and context metadata for an execution request.

    Carries tracing information from the caller. The executor uses this
    for audit correlation but does NOT make routing or auth decisions
    based on metadata -- those come from the auth proof and action type.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = ""
    session_id: str = ""
    sequence_id: int = 0
    timestamp: str = Field(default_factory=_utc_now)
    intent_frame_id: str | None = None
    task_description: str = ""


class ExecutionRequest(BaseModel):
    """Inbound execution request -- what arrives over the protocol boundary.

    Every field is validated by Pydantic on construction.
    Missing or invalid fields cause immediate rejection (fail-closed).

    Attributes:
        request_id: Unique identifier for this request (UUID4).
        action_type: The action to perform (e.g., "SEND_EMAIL", "READ_FILE").
        target: The target resource (e.g., virtual path, email address).
        params: Action-specific parameters.
        reason: Why the caller wants this action (for audit, not routing).
        authorization: Cryptographic proof that this request is authorized.
        metadata: Tracing and correlation metadata from the caller.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=_new_id)
    action_type: str = Field(
        ..., description="The action to perform (e.g., SEND_EMAIL, READ_FILE)"
    )
    target: str = Field(
        ..., description="The target resource (e.g., virtual path, email address)"
    )
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    authorization: AuthorizationProof
    metadata: RequestMetadata = Field(default_factory=RequestMetadata)


class ExecutionResult(BaseModel):
    """Outbound execution result -- what goes back over the protocol boundary.

    The gateway constructs this after adapter execution completes.
    On any failure (adapter error, timeout, auth failure), success=False
    and error contains a safe, non-credential-leaking description.

    Attributes:
        success: Whether the action completed successfully.
        data: Action-specific result data (None on failure).
        error: Human-readable error description (None on success).
        execution_id: Unique identifier for audit correlation.
        timestamp: When execution completed (ISO 8601 UTC).
        duration_ms: Wall-clock execution time in milliseconds.
        rollback_available: Whether this execution can be undone.
        rollback_id: ID to use for rollback request (if available).
        extras: Adapter-stamped metadata. For user-IO actions,
            the I/O adapter sets ``extras["user_response_token"]`` — a
            SHA-256 attestation that the user saw a prompt and responded.
    """

    model_config = ConfigDict(frozen=False)

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    execution_id: str = Field(default_factory=_new_id)
    timestamp: str = Field(default_factory=_utc_now)
    duration_ms: int | None = None
    rollback_available: bool = False
    rollback_id: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Models
# ═══════════════════════════════════════════════════════════════════════════════


class AuthResult(BaseModel):
    """Result of authorization verification.

    Returned by AuthVerifier.verify(). If valid=False, the gateway
    rejects the request immediately and logs a security event.
    """

    model_config = ConfigDict(frozen=True)

    valid: bool
    caller_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Audit & Security Models
# ═══════════════════════════════════════════════════════════════════════════════


class AuditEntry(BaseModel):
    """A single, immutable event in the append-only audit log.

    The audit log is fully append-only. Every row is an INSERT; no row
    is ever UPDATEd.  Each execution produces TWO entries:

        1. event=STARTED  -- logged before the adapter runs
        2. event=COMPLETED / FAILED / TIMED_OUT -- logged after

    Both entries share the same ``execution_id`` for correlation, but
    each is a distinct row with its own hash in the chain.  This means
    EVERY field is hash-protected -- tampering with any field in any
    row breaks the chain.

    IMPORTANT: params_hash is a SHA-256 hash of the params, NOT the raw
    params themselves. Credentials are NEVER stored in the audit log.
    """

    execution_id: str
    intent_frame_id: str | None = None
    action_type: str
    adapter_id: str
    status: ExecutionStatus
    params_hash: str = ""
    result_summary: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    timestamp: str = Field(default_factory=_utc_now)
    prev_hash: str = ""
    entry_hash: str = ""


class SecurityEvent(BaseModel):
    """Record of a security-relevant event.

    Logged when: invalid auth, unknown action, suspicious patterns,
    adapter crashes, rate limit exceeded, etc. These are stored
    separately from the audit log for security monitoring.
    """

    event_type: SecurityEventType
    source_info: str = ""
    details: str = ""
    timestamp: str = Field(default_factory=_utc_now)


class RollbackEntry(BaseModel):
    """A stored rollback capability for potential future undo.

    Created when an adapter reports rollback_available=True.
    Contains the data needed to reverse the action.
    Expires automatically after the configured window.
    """

    execution_id: str
    rollback_id: str = Field(default_factory=_new_id)
    adapter_id: str
    rollback_data: dict[str, Any] = Field(default_factory=dict)
    expires_at: str | None = None
    status: RollbackStatus = RollbackStatus.AVAILABLE
    created_at: str = Field(default_factory=_utc_now)


# ═══════════════════════════════════════════════════════════════════════════════
# Adapter Models
# ═══════════════════════════════════════════════════════════════════════════════


class AdapterManifest(BaseModel):
    """Declaration of an adapter's identity and capabilities.

    Every adapter exposes a manifest that the dispatcher uses
    for routing and the gateway uses for validation.
    """

    model_config = ConfigDict(frozen=True)

    adapter_id: str
    name: str
    description: str = ""
    supported_actions: list[str]
    requires_credentials: bool = False
    version: str = "1.0.0"
