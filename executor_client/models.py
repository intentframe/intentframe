"""
Client-side copies of the executor wire protocol.

These 4 models define the JSON shapes that cross the UDS boundary between
IntentFrame Core and the Executor service.  They mirror the protocol-boundary
models in executor/models.py but have **zero dependency on the executor
package**, so the client side never needs to import the server codebase.

If the wire format changes, update both this file and executor/models.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class AuthorizationProof(BaseModel):
    """Authorization proof attached to every execution request."""

    model_config = ConfigDict(frozen=True)

    scheme: str = Field(
        ..., description="Auth scheme: guardian_hmac, mtls, bearer, etc."
    )
    token: str = Field(
        ..., description="The auth token, signature, or certificate reference"
    )
    timestamp: str = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequestMetadata(BaseModel):
    """Origin and context metadata for an execution request."""

    model_config = ConfigDict(frozen=True)

    agent_id: str = ""
    session_id: str = ""
    sequence_id: int = 0
    timestamp: str = Field(default_factory=_utc_now)
    intent_frame_id: str | None = None
    task_description: str = ""


class ExecutionRequest(BaseModel):
    """Outbound execution request — what we send to the executor service."""

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
    """Inbound execution result — what we receive from the executor service.

    ``display_summary`` is forwarded unchanged to ``intentframe_core`` types
    for verbose pipeline output.
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
    display_summary: str = ""
