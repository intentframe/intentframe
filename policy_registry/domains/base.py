"""Base class for domain-level constraints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from action_registry.types import DomainType


class DomainConstraints(BaseModel):
    """Base for domain-level constraints (not per-action-type).

    Consumed by Guardian domain modules for deterministic structural
    enforcement before AI evaluation.
    """

    model_config = ConfigDict(frozen=True)

    domain: DomainType
