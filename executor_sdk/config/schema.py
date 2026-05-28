"""Public config fragments used by executor packs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HostFilesConfig(BaseModel):
    """Configuration for the HOST_FILE action family.

    The HOST_FILE adapter operates on real host filesystem paths rather
    than virtual-filesystem paths.  These allowlists are the executor-
    side ceiling — the per-action policy constraints
    (``HostFileConstraints.allowed_host_paths``) ride alongside and
    must not grant paths that this config denies.

    Both lists are normalized at load time via
    :func:`resource_registry.floor.canonicalize_real_path` so that a
    YAML-supplied ``~/Documents`` and a runtime-supplied
    ``/Users/<me>/Documents`` compare as the same path.

    These entries are executor-side *scope roots*, not policy-style
    glob patterns.  Nested access is admitted by subtree containment
    under the canonicalized root; trailing ``/`` carries no special
    meaning here because canonicalization strips it.

    This field is **required** on :class:`ExecutorConfig` (no default
    factory): host-file access is a security-sensitive surface and
    every executor YAML must declare intent explicitly.  Empty lists
    are permitted and mean "no host-file paths allowed" — paired with
    ``host_files`` absent from ``adapters.enabled`` that is the
    deliberate "demo declines host-file access" declaration.
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
