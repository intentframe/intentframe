"""Configuration schema for the POSIX VFS files adapter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FilesMount(BaseModel):
    """A single virtual-to-real path mapping for the files adapter."""

    model_config = ConfigDict(extra="forbid")

    virtual_path: str
    real_path: str
    writable: bool = False
    file_filter: str | None = None


class FilesConfig(BaseModel):
    """Configuration for the VFS file action family.

    The files adapter resolves agent-visible virtual paths (e.g. ``/home/``)
    to real host paths via the mount table.

    Mount resolution order:
    1. If ``workspace_id`` is set, attempt a live lookup from the resource
       registry ``executor_view``; fall back to ``mounts`` on any error.
    2. Otherwise use ``mounts`` directly (the common static-config path).

    ``base_path`` is the root used to resolve relative ``real_path`` values
    in ``mounts`` (equivalent to ``filesystem.base_path`` in the old schema).
    ``None`` defaults to ``Path.home()``.
    """

    model_config = ConfigDict(extra="forbid")

    base_path: str | None = Field(
        default=None,
        description=(
            "Base path for resolving relative mount real_paths. "
            "None = home directory."
        ),
    )
    mounts: list[FilesMount] = Field(
        default_factory=list,
        description="Static virtual-to-real path mount points.",
    )
    workspace_id: str | None = Field(
        default=None,
        description=(
            "Optional resource-registry workspace ID for dynamic mount "
            "resolution. When set the adapter queries executor_view at "
            "startup; on failure it falls back to the static mounts list."
        ),
    )
