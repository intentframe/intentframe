"""Constraints for FILE category actions (READ_FILE, WRITE_FILE, etc.)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileConstraints(BaseModel):
    """Virtual-path constraints for FILE category actions.

    Attributes:
        allowed_paths: Virtual path patterns the user permits.
            Supports exact match, prefix match (paths ending with /),
            and glob patterns (fnmatch).

    Note:
        ``extra="forbid"`` is required for defense-in-depth against
        the policy-schema disambiguation invariant (see
        ``HostFileConstraints``).  Payloads that accidentally mix
        ``allowed_paths`` and ``allowed_host_paths`` must fail loudly
        instead of silently selecting whichever Union member happens
        to match first.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_paths: list[str] = Field(min_length=1)
