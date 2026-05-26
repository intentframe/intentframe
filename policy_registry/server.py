"""
Policy Registry -- FastAPI server on Unix Domain Socket.

Wraps the in-memory PolicyRegistry with HTTP endpoints.
All business logic stays in registry.py; this is pure HTTP plumbing.

Routes are keyed on the ``(user_id, agent_id)`` pair:

    GET    /policies                                  → list all (user, agent) keys
    POST   /policies                                  → upsert (body has both ids)
    GET    /policies/{user_id}/{agent_id}             → policy (opaque constraints)
    GET    /policies/{user_id}/{agent_id}/permission  → single ActionPermission
    DELETE /policies/{user_id}/{agent_id}             → drop policy
    PATCH  /policies/{user_id}/{agent_id}/constraints → update one action's constraints

Startup:
    uvicorn policy_registry.server:app --uds ~/.intentframe/run/policy-registry.sock
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from policy_registry.models import ActionPermission, UserPolicy
from policy_registry.registry import PolicyRegistry

logger = logging.getLogger(__name__)

app = FastAPI(title="IntentFrame Policy Registry", version="0.4.0")
_registry = PolicyRegistry()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "policy-registry"}


@app.post("/policies", status_code=201)
async def set_user_policy(policy: UserPolicy) -> dict[str, str]:
    _registry.set_user_policy(policy)
    return {"status": "ok", "user_id": policy.user_id, "agent_id": policy.agent_id}


@app.get("/policies", response_model=list[tuple[str, str]])
async def list_users() -> list[tuple[str, str]]:
    return _registry.list_users()


@app.get("/policies/{user_id}/{agent_id}", response_model=UserPolicy)
async def get_user_policy(user_id: str, agent_id: str) -> UserPolicy:
    """Return the stored policy (opaque constraint dicts, no resolution)."""
    try:
        return _registry.get_user_policy(user_id, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/policies/{user_id}/{agent_id}/permission")
async def get_permission(
    user_id: str, agent_id: str, action: str
) -> Optional[ActionPermission]:
    try:
        return _registry.get_permission(user_id, agent_id, action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.delete("/policies/{user_id}/{agent_id}", status_code=204)
async def delete_user_policy(user_id: str, agent_id: str) -> None:
    _registry.delete_user_policy(user_id, agent_id)


class UpdateConstraintsRequest(BaseModel):
    """Generic constraint update — callers own the shape."""
    constraints: dict[str, Any] | None = None


@app.patch("/policies/{user_id}/{agent_id}/constraints")
async def update_action_constraints(
    user_id: str,
    agent_id: str,
    action: str,
    body: UpdateConstraintsRequest,
) -> dict[str, str]:
    """Replace the constraints dict for a single action (opaque)."""
    try:
        _registry.update_action_constraints(
            user_id, agent_id, action, body.constraints
        )
        return {"status": "ok"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


def get_registry() -> PolicyRegistry:
    """Access the underlying registry instance (for supervisor injection)."""
    return _registry
