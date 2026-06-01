"""Base class for typed intent data schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DomainSchema(BaseModel):
    """Base for domain intent slices validated against ``IntentFrame.data``.

    Each domain declares only the fields its policy cares about. Other keys in
    the action payload are ignored (``extra="ignore"``), so multiple domains can
    apply to the same action without sharing one exhaustive payload model.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    @classmethod
    def validate_slice(cls, data: dict[str, Any] | None) -> DomainSchema:
        """Validate this domain's slice of an action payload."""
        return cls.model_validate(data or {})
