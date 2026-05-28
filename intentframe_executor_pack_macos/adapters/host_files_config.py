"""Configuration schema for the macOS host-files adapter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HostFilesConfig(BaseModel):
    """Configuration for the HOST_FILE action family.

    The HOST_FILE adapter operates on real host filesystem paths rather
    than virtual-filesystem paths. These allowlists are the executor-side
    ceiling; the per-action policy constraints ride alongside and must not
    grant paths that this config denies.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_read_paths: list[str] = Field(
        description=(
            "Real-path scope roots (with ~ allowed) that host-file reads may "
            "touch; subtree access is granted by containment under each "
            "canonicalized root, not by glob or trailing-slash syntax."
        ),
    )
    allowed_write_paths: list[str] = Field(
        description=(
            "Real-path scope roots (with ~ allowed) that host-file "
            "writes/deletes may touch; subtree access is granted by "
            "containment under each canonicalized root, not by glob or "
            "trailing-slash syntax."
        ),
    )

    @field_validator("allowed_read_paths", "allowed_write_paths", mode="after")
    @classmethod
    def _canonicalize(cls, paths: list[str]) -> list[str]:
        """Expand ``~`` + resolve symlinks on each path once at load time."""
        from resource_registry.floor import canonicalize_real_path

        return [canonicalize_real_path(p) for p in paths]
