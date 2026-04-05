"""Base class for typed intent data schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DomainSchema(BaseModel):
    """Base for typed intent data schemas.

    Subclasses define required fields for their domain.
    Frozen to prevent mutation after validation.
    """

    model_config = ConfigDict(frozen=True)
