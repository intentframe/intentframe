"""
Resource Registry -- single source of truth for workspace configurations.

The registry sits between admin/user configuration and the runtime consumers
(agent clients and executor services).  It stores workspaces and projects
different views to different parties:

    Admin/User ──► Registry ──┬──► ClientView   (agent sees virtual paths)
                              └──► ExecutorView  (executor sees real paths)

In the demo this runs in-process with an in-memory store.
In production it becomes its own microservice backed by a database.

Usage (demo):
    from intentframe_native_kit.resource_registry import ResourceRegistry, ResourceMount

    registry = ResourceRegistry()

    registry.create_workspace(
        workspace_id="invoice_processing",
        mounts=[
            ResourceMount(virtual_path="/invoices/", real_path="demo_data", file_filter="*.md"),
            ResourceMount(virtual_path="/expense_tracker.md", real_path="demo_data/expense_tracker.md", writable=True),
        ],
        base_path="/path/to/demo",
    )

    client_view   = registry.client_view("invoice_processing")
    executor_view = registry.executor_view("invoice_processing")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from intentframe_native_kit.resource_registry.models import (
    ClientView,
    ExecutorView,
    ResourceMount,
    Workspace,
)

logger = logging.getLogger(__name__)

__all__ = ["ResourceRegistry"]


class ResourceRegistry:
    """In-memory resource registry.

    Stores workspaces and projects client/executor views on demand.
    The store is pluggable -- swap ``_workspaces`` with a DB-backed
    dict-like object for production.
    """

    def __init__(self) -> None:
        self._workspaces: dict[str, Workspace] = {}

    # ── Workspace CRUD ────────────────────────────────────────────────

    def create_workspace(
        self,
        workspace_id: str,
        mounts: list[ResourceMount],
        base_path: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Workspace:
        """Create and register a new workspace.

        Args:
            workspace_id: Unique identifier for the workspace.
            mounts: List of virtual-to-real resource mappings.
            base_path: Root for resolving relative ``real_path`` values.
            metadata: Optional key-value pairs (owner, description, etc.).

        Returns:
            The created Workspace.

        Raises:
            ValueError: If a workspace with the same ID already exists.
        """
        if workspace_id in self._workspaces:
            raise ValueError(f"Workspace '{workspace_id}' already exists")

        workspace = Workspace(
            workspace_id=workspace_id,
            mounts=list(mounts),
            base_path=str(base_path) if base_path is not None else None,
            metadata=metadata or {},
        )
        self._workspaces[workspace_id] = workspace

        logger.info(
            "Workspace '%s' created: %d mounts, base_path=%s",
            workspace_id,
            len(mounts),
            base_path,
        )
        return workspace

    def get_workspace(self, workspace_id: str) -> Workspace:
        """Retrieve a workspace by ID.

        Raises:
            KeyError: If the workspace does not exist.
        """
        try:
            return self._workspaces[workspace_id]
        except KeyError:
            raise KeyError(f"Workspace '{workspace_id}' not found") from None

    def delete_workspace(self, workspace_id: str) -> None:
        """Remove a workspace from the registry."""
        self._workspaces.pop(workspace_id, None)

    def list_workspaces(self) -> list[str]:
        """Return all registered workspace IDs."""
        return list(self._workspaces.keys())

    # ── View Projections ──────────────────────────────────────────────

    def client_view(self, workspace_id: str) -> ClientView:
        """Project the client/agent view of a workspace.

        Returns only virtual paths and permissions -- no real paths.
        This is what gets sent to the agent at handshake time.
        """
        workspace = self.get_workspace(workspace_id)

        virtual_paths = [m.virtual_path for m in workspace.mounts]
        permissions = {
            m.virtual_path: "read_write" if m.writable else "read"
            for m in workspace.mounts
        }

        return ClientView(
            workspace_id=workspace_id,
            virtual_paths=virtual_paths,
            permissions=permissions,
        )

    def executor_view(self, workspace_id: str) -> ExecutorView:
        """Project the executor view of a workspace.

        Returns the full mount table with real paths.
        Only the executor service should call this.
        """
        workspace = self.get_workspace(workspace_id)

        return ExecutorView(
            workspace_id=workspace_id,
            mounts=list(workspace.mounts),
            base_path=Path(workspace.base_path) if workspace.base_path else None,
        )
