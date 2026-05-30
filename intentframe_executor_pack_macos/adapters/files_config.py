"""Files adapter config (re-exported from the portable POSIX pack).

The schema moved to ``intentframe_executor_pack_posix.adapters.files_config`` so
it can be shared across deployments. This module remains for backward-compatible
imports.
"""

from __future__ import annotations

from intentframe_executor_pack_posix.adapters.files_config import (
    FilesConfig,
    FilesMount,
)

__all__ = ["FilesConfig", "FilesMount"]
