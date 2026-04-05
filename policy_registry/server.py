"""
Policy Registry -- FastAPI server on Unix Domain Socket.

Wraps the in-memory PolicyRegistry with HTTP endpoints.
All business logic stays in registry.py; this is pure HTTP plumbing.

Startup:
    uvicorn policy_registry.server:app --uds ~/.intentframe/run/policy-registry.sock
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from policy_registry.models import ActionPermission, UserPolicy
from policy_registry.registry import PolicyRegistry
from policy_registry.constraints.email import EmailConstraints, RecipientSource
from policy_registry.constraints.message import MessageConstraints, ContactSource

logger = logging.getLogger(__name__)

app = FastAPI(title="IntentFrame Policy Registry", version="0.2.0")
_registry = PolicyRegistry()


class HealthResponse:
    status: str = "ok"
    service: str = "policy-registry"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "policy-registry"}


@app.post("/policies", status_code=201)
async def set_user_policy(policy: UserPolicy) -> dict[str, str]:
    _registry.set_user_policy(policy)
    return {"status": "ok", "user_id": policy.user_id}


@app.get("/policies", response_model=list[str])
async def list_users() -> list[str]:
    return _registry.list_users()


@app.get("/policies/{user_id}", response_model=UserPolicy)
async def get_user_policy(user_id: str) -> UserPolicy:
    """Return user policy with all dynamic sources resolved into flat lists."""
    try:
        return await _registry.get_user_policy_resolved(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/policies/{user_id}/raw", response_model=UserPolicy)
async def get_user_policy_raw(user_id: str) -> UserPolicy:
    """Return user policy without source resolution (for management UIs)."""
    try:
        return _registry.get_user_policy(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/policies/{user_id}/permission")
async def get_permission(
    user_id: str, action: str
) -> Optional[ActionPermission]:
    try:
        return _registry.get_permission(user_id, action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.delete("/policies/{user_id}", status_code=204)
async def delete_user_policy(user_id: str) -> None:
    _registry.delete_user_policy(user_id)



# ── Request bodies for management endpoints ─────────────────────────

class PatchRecipientsRequest(BaseModel):
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class AddSourceRequest(BaseModel):
    source: str
    filter: str = ""
    enabled: bool = True


class RemoveSourceRequest(BaseModel):
    source: str
    filter: str = ""


# ── Email constraint management ─────────────────────────────────────

@app.patch("/policies/{user_id}/constraints/email")
async def patch_email_recipients(
    user_id: str,
    body: PatchRecipientsRequest,
    action: str = "SEND_EMAIL",
) -> dict:
    try:
        updated = _registry.patch_email_recipients(
            user_id, action, add=body.add, remove=body.remove
        )
        return {"status": "ok", "allowed_recipients": updated.allowed_recipients}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/policies/{user_id}/constraints/email/sources", status_code=201)
async def add_email_source(
    user_id: str,
    body: AddSourceRequest,
    action: str = "SEND_EMAIL",
) -> dict:
    try:
        src = RecipientSource(source=body.source, filter=body.filter, enabled=body.enabled)
        updated = _registry.add_email_source(user_id, action, src)
        return {
            "status": "ok",
            "recipient_sources": [s.model_dump() for s in updated.recipient_sources],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.delete("/policies/{user_id}/constraints/email/sources")
async def delete_email_source(
    user_id: str,
    body: RemoveSourceRequest,
    action: str = "SEND_EMAIL",
) -> dict:
    try:
        updated = _registry.remove_email_source(
            user_id, action, body.source, body.filter
        )
        return {
            "status": "ok",
            "recipient_sources": [s.model_dump() for s in updated.recipient_sources],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/policies/{user_id}/constraints/email/resolved")
async def get_resolved_email_recipients(
    user_id: str,
    action: str = "SEND_EMAIL",
) -> dict:
    """Preview the fully resolved recipient list (explicit + sources)."""
    try:
        resolved_policy = await _registry.get_user_policy_resolved(user_id)
        perm = resolved_policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, EmailConstraints):
            raise HTTPException(status_code=404, detail=f"No EmailConstraints for {action}")
        return {
            "action": action,
            "allowed_recipients": perm.constraints.allowed_recipients,
            "count": len(perm.constraints.allowed_recipients),
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


# ── Message constraint management ───────────────────────────────────

@app.patch("/policies/{user_id}/constraints/message")
async def patch_message_contacts(
    user_id: str,
    body: PatchRecipientsRequest,
    action: str = "SEND_MESSAGE",
) -> dict:
    try:
        updated = _registry.patch_message_contacts(
            user_id, action, add=body.add, remove=body.remove
        )
        return {"status": "ok", "allowed_contacts": updated.allowed_contacts}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/policies/{user_id}/constraints/message/sources", status_code=201)
async def add_message_source(
    user_id: str,
    body: AddSourceRequest,
    action: str = "SEND_MESSAGE",
) -> dict:
    try:
        src = ContactSource(source=body.source, filter=body.filter, enabled=body.enabled)
        updated = _registry.add_message_source(user_id, action, src)
        return {
            "status": "ok",
            "contact_sources": [s.model_dump() for s in updated.contact_sources],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.delete("/policies/{user_id}/constraints/message/sources")
async def delete_message_source(
    user_id: str,
    body: RemoveSourceRequest,
    action: str = "SEND_MESSAGE",
) -> dict:
    try:
        updated = _registry.remove_message_source(
            user_id, action, body.source, body.filter
        )
        return {
            "status": "ok",
            "contact_sources": [s.model_dump() for s in updated.contact_sources],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/policies/{user_id}/constraints/message/resolved")
async def get_resolved_message_contacts(
    user_id: str,
    action: str = "SEND_MESSAGE",
) -> dict:
    """Preview the fully resolved contact list (explicit + sources)."""
    try:
        resolved_policy = await _registry.get_user_policy_resolved(user_id)
        perm = resolved_policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, MessageConstraints):
            raise HTTPException(status_code=404, detail=f"No MessageConstraints for {action}")
        return {
            "action": action,
            "allowed_contacts": perm.constraints.allowed_contacts,
            "count": len(perm.constraints.allowed_contacts),
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


def get_registry() -> PolicyRegistry:
    """Access the underlying registry instance (for supervisor injection)."""
    return _registry
