"""
Policy contract types shared across the pipeline.

These are pure, frozen Pydantic models with no registry or service
dependencies. ``UserPolicy`` (the aggregate) lives in ``policy_registry``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SemanticIntentLimit(BaseModel):
    """A human-level restriction the AI Guardian evaluates against.

    Not a rules engine. A reference sheet the AI reads when making decisions.
    The AI handles the understanding (is this intent spending money?).
    The limit provides the boundary (spending limit is $5k).
    """

    model_config = ConfigDict(frozen=True)

    limit_id: str
    domain: str
    description: str
    raw: str

    threshold: Optional[float] = None
    pattern: Optional[str] = None
    effect: str = "block"
    scope: str = "per_action"


class ActionPermission(BaseModel):
    """Permission entry for a single action type.

    Attributes:
        safe: User trusts this action enough for fast (code-only) validation.
              When False, consumers should use thorough validation (e.g. AI).
        constraints: Category-specific constraints (paths, amounts, etc.).
              None means no constraints — the action is allowed unconditionally.
    """

    model_config = ConfigDict(frozen=True)

    safe: bool = False
    constraints: dict[str, Any] | None = None
