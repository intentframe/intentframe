"""SQLite audit logger (re-exported from the portable POSIX pack).

The implementation moved to ``intentframe_executor_pack_posix.audit_logger`` so
it can be shared across deployments. This module remains for backward-compatible
imports.
"""

from __future__ import annotations

from intentframe_executor_pack_posix.audit_logger import SQLiteAuditLogger

__all__ = ["SQLiteAuditLogger"]
