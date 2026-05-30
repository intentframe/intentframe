"""Guardian HMAC verifier (re-exported from the portable POSIX pack).

The implementation moved to ``intentframe_executor_pack_posix.auth`` so it can
be shared across deployments. This module remains for backward-compatible
imports.
"""

from __future__ import annotations

from intentframe_executor_pack_posix.auth import GuardianHMACVerifier

__all__ = ["GuardianHMACVerifier"]
