"""Local virtual filesystem (re-exported from the portable POSIX pack).

The implementation moved to ``intentframe_native_kit.intentframe_executor_pack_posix.virtual_filesystem``
so it can be shared across deployments. This module remains for
backward-compatible imports.
"""

from __future__ import annotations

from intentframe_native_kit.intentframe_executor_pack_posix.virtual_filesystem import (
    LocalVirtualFileSystem,
    _canonical_real_path,
)

__all__ = ["LocalVirtualFileSystem", "_canonical_real_path"]
