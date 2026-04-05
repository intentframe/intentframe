"""
Policy Registry Models

The user's source of truth for what actions are allowed on this device.

Key types:
    ActionPermission -- Permission for a single action type.
    UserPolicy       -- Complete policy set for a user.

Design:
    - Present in allowed_actions → ALLOWED (with optional constraints).
    - Absent from allowed_actions → BLOCKED (deny-by-default).
    - No "decision" field. The data structure IS the permission.
    - Constraints are per-category (FileConstraints, EmailConstraints, etc.)
    - The ``safe`` flag lets the user declare trust level for fast validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

from policy_registry.constraints import (
    ApiConstraints,
    BrowserConstraints,
    CalendarConstraints,
    EmailConstraints,
    FileConstraints,
    MessageConstraints,
    TerminalConstraints,
)
from policy_registry.domains.base import DomainConstraints
from policy_registry.domains.finance import FinanceConstraints
from policy_registry.domains.deletion import DeletionConstraints

ConstraintTypes = Union[
    FileConstraints,
    TerminalConstraints,
    EmailConstraints,
    CalendarConstraints,
    MessageConstraints,
    BrowserConstraints,
    ApiConstraints,
]

DomainConstraintTypes = Annotated[
    Union[
        Annotated[FinanceConstraints, Tag("finance")],
        Annotated[DeletionConstraints, Tag("deletion")],
    ],
    Discriminator(lambda v: v.get("domain", v) if isinstance(v, dict) else v.domain),
]


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
    constraints: Optional[ConstraintTypes] = Field(default=None, discriminator=None)


class UserPolicy(BaseModel):
    """Complete policy configuration for a user.

    The allowed_actions dict is the entire policy:
    - Key: ActionType value string (e.g. "READ_FILE").
    - Value: ActionPermission with optional constraints.
    - Absent key: action is BLOCKED (deny-by-default).

    Attributes:
        user_id: Unique identifier for the user.
        allowed_actions: Map of action type → permission.
        metadata: Optional key-value pairs (department, role, etc.).
        created_at: ISO timestamp of when the policy was created.
    """

    user_id: str
    allowed_actions: dict[str, ActionPermission] = Field(default_factory=dict)
    intent_limits: list[SemanticIntentLimit] = Field(default_factory=list)
    domain_constraints: dict[str, DomainConstraintTypes] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def is_allowed(self, action_type: str) -> bool:
        """Check if an action type is in the allowed set."""
        return action_type in self.allowed_actions

    def get_permission(self, action_type: str) -> Optional[ActionPermission]:
        """Get the permission for an action type, or None if blocked."""
        return self.allowed_actions.get(action_type)
