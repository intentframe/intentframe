"""
Policy Registry Models

The user's source of truth for what actions are allowed on this device.

Key types:
    ActionPermission, SemanticIntentLimit -- re-exported from intentframe_core.policy.
    UserPolicy       -- Complete policy set for a user.

Design:
    - Present in allowed_actions → ALLOWED (with optional constraints).
    - Absent from allowed_actions → BLOCKED (deny-by-default).
    - No "decision" field. The data structure IS the permission.
    - Constraints are opaque dicts per action or category; registered bundles
      validate shape at startup via the Bundle SDK.
    - The ``safe`` flag lets the user declare trust level for fast validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field, StringConstraints

from intentframe_core.policy import ActionPermission, SemanticIntentLimit

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

# Schema version for IntentFrame policy YAMLs.  Bump when the YAML
# shape changes in a backwards-incompatible way (renamed/removed
# fields, new required fields, semantic shifts).  The loader hard-
# fails on mismatch with a friendly error so users with stale YAMLs
# get a clear migration signal instead of a Pydantic stacktrace.
INTENTFRAME_POLICY_SCHEMA_VERSION: int = 1


class UserPolicy(BaseModel):
    """Complete policy configuration for one (user, agent) pair.

    The allowed_actions dict is the entire policy:
    - Key: ActionType value string (e.g. "READ_FILE").
    - Value: ActionPermission with optional constraints.
    - Absent key: action is BLOCKED (deny-by-default).

    Identity model:
        ``user_id`` identifies the human/operator who owns this policy.
        ``agent_id`` identifies which agent the policy applies to.
        The registry keys on the ``(user_id, agent_id)`` pair, so a
        single user can run multiple agents (e.g. ``jarvis``,
        ``invoice_bot``) with distinct, isolated policies.

    Attributes:
        user_id: Unique identifier for the user/operator.
        agent_id: Identifier of the agent this policy governs
            (e.g. ``jarvis``, ``jarvis_root``, ``invoice_bot``).
            Required and must match what the agent presents during
            handshake; the registry uses it as part of the lookup key.
        intentframe_schema_version: YAML schema version this policy was
            authored against.  Defaults to the running IntentFrame
            version for in-code construction; the YAML loader requires
            it to be present and matching.
        allowed_actions: Map of action type → permission.
        metadata: Optional key-value pairs (department, role, etc.).
        created_at: ISO timestamp of when the policy was created.
    """

    # ``min_length=1`` defends against silent slot collisions: an
    # empty id would alias every "unset" caller into the same registry
    # slot, masking missing-id bugs in client code.  Loaders that
    # explicitly require an id (Actor SDK, Bootstrapper, demo loader)
    # already raise on missing values; this is the model-level backstop.
    user_id: NonEmptyStr
    agent_id: NonEmptyStr
    intentframe_schema_version: int = INTENTFRAME_POLICY_SCHEMA_VERSION
    allowed_actions: dict[str, ActionPermission] = Field(default_factory=dict)
    intent_limits: list[SemanticIntentLimit] = Field(default_factory=list)
    domain_constraints: dict[str, dict[str, Any]] = Field(default_factory=dict)
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
