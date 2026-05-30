"""Unix domain socket transport (re-exported from the portable POSIX pack).

The implementation moved to ``intentframe_executor_pack_posix.transport`` so it
can be shared across Linux/container/cloud deployments. This module remains for
backward-compatible imports.
"""

from __future__ import annotations

from intentframe_executor_pack_posix.transport import UnixSocketTransport

__all__ = ["UnixSocketTransport"]
