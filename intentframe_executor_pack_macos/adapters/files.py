"""Files adapter (re-exported from the portable POSIX pack).

The implementation moved to ``intentframe_executor_pack_posix.adapters.files``
so it can be shared across deployments. This module remains for
backward-compatible imports.
"""

from __future__ import annotations

from intentframe_executor_pack_posix.adapters.files import (
    FilesAdapter,
    _mounts_from_config,
)

__all__ = ["FilesAdapter", "_mounts_from_config"]
