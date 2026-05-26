"""
Policy Registry -- central store for user-defined policies.

The registry sits between the user and everything else on the device.
It is a *data store only* -- it does not make allow/block decisions.
Consumers (IntentFrame's Guardian, other apps) read from it.

    User ──► PolicyRegistry ──► Guardian (reads policies, decides)
                             ──► Analysis Engine (reads policies, adjusts depth)

Identity model
--------------
Policies are keyed on the ``(user_id, agent_id)`` pair.  One operator
running multiple agents (``jarvis``, ``invoice_bot``, ...) gets one
isolated policy slot per agent — they never collide and never fall
back to each other.

In the demo this runs in-process with an in-memory store.
In production it becomes its own microservice backed by a database,
with a user-facing API (dashboard, CLI, SDK).

Usage (demo):

    from policy_registry import PolicyRegistry, UserPolicy, ActionPermission

    registry = PolicyRegistry()

    registry.set_user_policy(UserPolicy(
        user_id="finance_001",
        agent_id="invoice_bot",
        allowed_actions={
            "READ_FILE": ActionPermission(
                safe=True,
                constraints={"allowed_paths": ["/invoices/"]},
            ),
            "ASK_USER": ActionPermission(safe=True),
            "PAY_INVOICE": ActionPermission(safe=False),
        },
    ))

    policy = registry.get_user_policy("finance_001", "invoice_bot")
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from policy_registry.models import ActionPermission, UserPolicy

logger = logging.getLogger(__name__)

__all__ = ["PolicyRegistry"]


# Composite (user_id, agent_id) key used internally.
PolicyKey = tuple[str, str]


def _key_of(policy: UserPolicy) -> PolicyKey:
    return (policy.user_id, policy.agent_id)


def _clone_policy(
    base: UserPolicy,
    *,
    allowed_actions: dict[str, ActionPermission] | None = None,
) -> UserPolicy:
    """Shallow clone of ``base`` with optional ``allowed_actions`` swap.

    Centralises the field list so future additions to :class:`UserPolicy`
    only need updating in one place.
    """
    return UserPolicy(
        user_id=base.user_id,
        agent_id=base.agent_id,
        intentframe_schema_version=base.intentframe_schema_version,
        allowed_actions=(
            allowed_actions if allowed_actions is not None else base.allowed_actions
        ),
        intent_limits=base.intent_limits,
        domain_constraints=base.domain_constraints,
        metadata=base.metadata,
        created_at=base.created_at,
    )


class PolicyRegistry:
    """In-memory policy registry.

    Stores per-(user, agent) policies and exposes simple query methods.
    The store is pluggable -- swap ``_policies`` with a DB-backed
    dict-like object for production.

    Constraints are stored and returned as opaque dicts.  Schema
    validation and runtime enforcement are the responsibility of the
    action bundles that own each constraint shape.
    """

    def __init__(self) -> None:
        self._policies: dict[PolicyKey, UserPolicy] = {}

    # ── CRUD ──────────────────────────────────────────────────────────

    def set_user_policy(self, policy: UserPolicy) -> None:
        """Create or replace the policy for a (user, agent) pair.

        The key is derived from ``policy.user_id`` and ``policy.agent_id``.
        """
        key = _key_of(policy)
        self._policies[key] = policy
        logger.info(
            "Policy set for user=%r agent=%r: %d allowed actions",
            policy.user_id,
            policy.agent_id,
            len(policy.allowed_actions),
        )

    def get_user_policy(self, user_id: str, agent_id: str) -> UserPolicy:
        """Retrieve the policy for a (user, agent) pair.

        Raises:
            KeyError: If no policy exists for the pair.
        """
        try:
            return self._policies[(user_id, agent_id)]
        except KeyError:
            raise KeyError(
                f"No policy found for user={user_id!r} agent={agent_id!r}"
            ) from None

    def delete_user_policy(self, user_id: str, agent_id: str) -> None:
        """Remove the policy for a (user, agent) pair."""
        self._policies.pop((user_id, agent_id), None)

    def list_users(self) -> list[PolicyKey]:
        """Return all ``(user_id, agent_id)`` pairs that have policies configured."""
        return list(self._policies.keys())

    # ── Query helpers (data retrieval, not decisions) ─────────────────

    def get_permission(
        self, user_id: str, agent_id: str, action_type: str
    ) -> Optional[ActionPermission]:
        """Get the permission for a specific action, or None if blocked.

        The caller is responsible for interpreting the result.
        """
        policy = self.get_user_policy(user_id, agent_id)
        return policy.get_permission(action_type)

    def is_action_allowed(
        self, user_id: str, agent_id: str, action_type: str
    ) -> bool:
        """Check whether an action is in the user's allowed set."""
        policy = self.get_user_policy(user_id, agent_id)
        return policy.is_allowed(action_type)

    def update_action_constraints(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        constraints: dict[str, Any] | None,
    ) -> None:
        """Replace the constraints dict for a single action.

        Callers own the constraint shape; the registry stores it opaquely.
        """
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None:
            raise KeyError(
                f"Action '{action}' not in policy for user={user_id!r} agent={agent_id!r}"
            )
        updated_perm = ActionPermission(safe=perm.safe, constraints=constraints)
        updated_actions = dict(policy.allowed_actions)
        updated_actions[action] = updated_perm
        self._policies[(user_id, agent_id)] = _clone_policy(
            policy, allowed_actions=updated_actions
        )
