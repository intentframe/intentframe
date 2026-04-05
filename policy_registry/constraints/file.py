"""Constraints for FILE category actions (READ_FILE, WRITE_FILE, etc.)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileConstraints(BaseModel):
    """Path-based constraints for file operations.

    Attributes:
        allowed_paths: Virtual path patterns the user permits.
            Supports exact match, prefix match (paths ending with /),
            and glob patterns (fnmatch).
    """

    model_config = ConfigDict(frozen=True)

    allowed_paths: list[str] = Field(min_length=1)
