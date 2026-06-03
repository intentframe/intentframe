"""Domain constraints for the deletion domain (plugin-local schema)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class DeletionConstraints(BaseModel):
    """User-configured limits for the deletion domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    require_confirmation: bool = True
    allowed_paths: Optional[list[str]] = None
    block_irreversible: bool = False
