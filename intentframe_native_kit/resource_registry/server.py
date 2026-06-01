"""
Resource Registry -- FastAPI server on Unix Domain Socket.

Wraps the in-memory ResourceRegistry with HTTP endpoints.
All business logic stays in registry.py; this is pure HTTP plumbing.

Startup:
    uvicorn intentframe_native_kit.resource_registry.server:app --uds ~/.intentframe/run/resource-registry.sock
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from intentframe_native_kit.resource_registry.models import (
    ClientView,
    ExecutorView,
    ResourceMount,
    Workspace,
)
from intentframe_native_kit.resource_registry.registry import ResourceRegistry

logger = logging.getLogger(__name__)

app = FastAPI(title="IntentFrame Resource Registry", version="0.1.0")
_registry = ResourceRegistry()


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "resource-registry"


class CreateWorkspaceRequest(BaseModel):
    workspace_id: str
    mounts: list[ResourceMount]
    base_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/workspaces", response_model=Workspace, status_code=201)
async def create_workspace(req: CreateWorkspaceRequest) -> Workspace:
    try:
        return _registry.create_workspace(
            workspace_id=req.workspace_id,
            mounts=req.mounts,
            base_path=req.base_path,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/workspaces", response_model=list[str])
async def list_workspaces() -> list[str]:
    return _registry.list_workspaces()


@app.get("/workspaces/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: str) -> Workspace:
    try:
        return _registry.get_workspace(workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/workspaces/{workspace_id}/client-view", response_model=ClientView)
async def client_view(workspace_id: str) -> ClientView:
    try:
        return _registry.client_view(workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.get("/workspaces/{workspace_id}/executor-view")
async def executor_view(workspace_id: str) -> dict:
    """Return executor view as dict (Path is not JSON-native)."""
    try:
        view = _registry.executor_view(workspace_id)
        data = {
            "workspace_id": view.workspace_id,
            "mounts": [m.model_dump() for m in view.mounts],
            "base_path": str(view.base_path) if view.base_path else None,
        }
        return data
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str) -> None:
    _registry.delete_workspace(workspace_id)


def get_registry() -> ResourceRegistry:
    """Access the underlying registry instance (for supervisor injection)."""
    return _registry
