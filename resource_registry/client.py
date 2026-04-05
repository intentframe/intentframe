"""
Resource Registry -- HTTP client over Unix Domain Socket.

Drop-in replacement for the in-process ResourceRegistry.
Same method signatures, but calls the resource-registry service over HTTP/UDS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from resource_registry.models import (
    ClientView,
    ExecutorView,
    ResourceMount,
    Workspace,
)

DEFAULT_SOCKET = "~/.intentframe/run/resource-registry.sock"


class ResourceRegistryClient:
    """HTTP client that mirrors the ResourceRegistry interface.

    Uses httpx with UDS transport to talk to the resource-registry service.
    """

    def __init__(self, socket_path: str = DEFAULT_SOCKET) -> None:
        import os
        self._socket = os.path.expanduser(socket_path)
        self._transport = httpx.HTTPTransport(uds=self._socket)
        self._client = httpx.Client(
            transport=self._transport,
            base_url="http://resource-registry",
            timeout=10.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def create_workspace(
        self,
        workspace_id: str,
        mounts: list[ResourceMount],
        base_path: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workspace:
        payload = {
            "workspace_id": workspace_id,
            "mounts": [m.model_dump() for m in mounts],
            "base_path": str(base_path) if base_path is not None else None,
            "metadata": metadata or {},
        }
        resp = self._client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            raise ValueError(resp.json().get("detail", "Workspace already exists"))
        resp.raise_for_status()
        return Workspace.model_validate(resp.json())

    def get_workspace(self, workspace_id: str) -> Workspace:
        resp = self._client.get(f"/workspaces/{workspace_id}")
        if resp.status_code == 404:
            raise KeyError(f"Workspace '{workspace_id}' not found")
        resp.raise_for_status()
        return Workspace.model_validate(resp.json())

    def delete_workspace(self, workspace_id: str) -> None:
        resp = self._client.delete(f"/workspaces/{workspace_id}")
        resp.raise_for_status()

    def list_workspaces(self) -> list[str]:
        resp = self._client.get("/workspaces")
        resp.raise_for_status()
        return resp.json()

    def client_view(self, workspace_id: str) -> ClientView:
        resp = self._client.get(f"/workspaces/{workspace_id}/client-view")
        if resp.status_code == 404:
            raise KeyError(f"Workspace '{workspace_id}' not found")
        resp.raise_for_status()
        return ClientView.model_validate(resp.json())

    def executor_view(self, workspace_id: str) -> ExecutorView:
        resp = self._client.get(f"/workspaces/{workspace_id}/executor-view")
        if resp.status_code == 404:
            raise KeyError(f"Workspace '{workspace_id}' not found")
        resp.raise_for_status()
        data = resp.json()
        mounts = [ResourceMount.model_validate(m) for m in data["mounts"]]
        base_path = Path(data["base_path"]) if data.get("base_path") else None
        return ExecutorView(
            workspace_id=data["workspace_id"],
            mounts=mounts,
            base_path=base_path,
        )
