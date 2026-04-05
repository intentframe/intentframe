"""
Resource Registry Models

Defines the data structures for workspace and resource management.
These models are independent of both the demo and executor packages,
allowing the registry to be extracted into its own microservice later.

Key types:
    ResourceMount  -- Admin-defined mapping: virtual path -> real storage
    Workspace      -- A named collection of ResourceMounts
    ClientView     -- What the agent/client sees (virtual paths only)
    ExecutorView   -- What the executor sees (full mount table)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResourceMount(BaseModel):
    """A single resource mapping within a workspace.

    Created by admin/user to define what an agent can access
    and where it actually lives on the executor's storage.

    The agent never sees ``real_path`` -- only ``virtual_path``.
    """

    model_config = ConfigDict(frozen=True)

    virtual_path: str
    real_path: str
    writable: bool = False
    file_filter: str | None = None


class Workspace(BaseModel):
    """A workspace defines the complete resource environment for an agent session.

    Created by admin/user through the registry.  The registry distributes
    different *views* of the workspace to different consumers:
        - Client/Agent  -> ClientView  (virtual paths + permissions)
        - Executor      -> ExecutorView (full mount table + real paths)

    Attributes:
        workspace_id: Unique identifier for this workspace.
        mounts: List of resource mounts (virtual -> real mappings).
        base_path: Base path for resolving relative real_path values.
                   In production this would be the executor's storage root.
        metadata: Optional key-value metadata (owner, description, etc.).
        created_at: ISO timestamp of when the workspace was created.
    """

    workspace_id: str
    mounts: list[ResourceMount] = Field(default_factory=list)
    base_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class ClientView(BaseModel):
    """The client/agent's view of a workspace -- virtual paths only.

    No real filesystem paths leak through this projection.
    This is what gets sent to the agent at handshake time.

    Attributes:
        workspace_id: Which workspace this view belongs to.
        virtual_paths: List of virtual paths the agent can reference.
        permissions: Per-path permission map (e.g. "read" or "read_write").
    """

    model_config = ConfigDict(frozen=True)

    workspace_id: str
    virtual_paths: list[str] = Field(default_factory=list)
    permissions: dict[str, str] = Field(default_factory=dict)


class ExecutorView(BaseModel):
    """The executor's view of a workspace -- full mount table.

    Only the executor service receives this projection.
    Contains real filesystem paths needed for actual I/O.

    Attributes:
        workspace_id: Which workspace this view belongs to.
        mounts: Full resource mounts with real paths.
        base_path: Base path for resolving relative real_path values.
    """

    model_config = ConfigDict(frozen=True)

    workspace_id: str
    mounts: list[ResourceMount] = Field(default_factory=list)
    base_path: Path | None = None
