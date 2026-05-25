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
        ``extra="forbid"`` rejects unknown fields (see
        ``HostFileConstraints``).  At startup, the files bundle's
        ``validate_constraints`` parses policy dicts with this schema;
        mixed ``allowed_paths`` and ``allowed_host_paths`` fail loudly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_paths: list[str] = Field(min_length=1)
