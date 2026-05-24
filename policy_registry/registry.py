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
    from policy_registry.constraints import FileConstraints

    registry = PolicyRegistry()

    registry.set_user_policy(UserPolicy(
        user_id="finance_001",
        agent_id="invoice_bot",
        allowed_actions={
            "READ_FILE": ActionPermission(
                safe=True,
                constraints=FileConstraints(allowed_paths=["/invoices/"]),
            ),
            "ASK_USER": ActionPermission(safe=True),
            "PAY_INVOICE": ActionPermission(safe=False),
        },
    ))

    policy = registry.get_user_policy("finance_001", "invoice_bot")
"""

from __future__ import annotations

import logging
from typing import Optional

from policy_registry.models import ActionPermission, UserPolicy
from policy_registry.contacts_client import PlatformContactsClient
from policy_registry.constraints.email import EmailConstraints, RecipientSource
from policy_registry.constraints.message import MessageConstraints, ContactSource
from policy_registry.constraints.terminal import TerminalConstraints

logger = logging.getLogger(__name__)

__all__ = ["PolicyRegistry"]

# System-level blocked command patterns. These are merged into every user's
# TerminalConstraints on read. Users can append additional patterns but
# cannot remove these. This is the policy registry's own safety floor.
SYSTEM_TERMINAL_BLOCKED_PATTERNS: tuple[str, ...] = (
    "sudo",
    "rm -rf /",
    "mkfs",
    "dd if=",
    "> /dev/",
    "chmod 777",
)


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

    Source resolution: when a policy contains RecipientSource or
    ContactSource rules, get_user_policy_resolved() resolves them into
    flat lists via the PlatformContactsClient before returning.
    """

    def __init__(self) -> None:
        self._policies: dict[PolicyKey, UserPolicy] = {}
        self._contacts_client = PlatformContactsClient()

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
        """Retrieve the raw (unresolved) policy for a (user, agent) pair.

        Raises:
            KeyError: If no policy exists for the pair.
        """
        try:
            return self._policies[(user_id, agent_id)]
        except KeyError:
            raise KeyError(
                f"No policy found for user={user_id!r} agent={agent_id!r}"
            ) from None

    async def get_user_policy_resolved(
        self, user_id: str, agent_id: str
    ) -> UserPolicy:
        """Retrieve the policy with system floors enforced and sources resolved.

        1. Merges system-level defaults (blocked patterns, etc.) that users
           cannot remove — only append to.
        2. Resolves RecipientSource / ContactSource rules via the platform
           server into flat lists.

        Consumers (Guardian, Analysis Engine, etc.) only see resolved data.
        """
        policy = self.get_user_policy(user_id, agent_id)
        policy = self._enforce_system_floor(policy)
        return await self._resolve_sources(policy)

    @staticmethod
    def _enforce_system_floor(policy: UserPolicy) -> UserPolicy:
        """Merge system-level defaults into the user's policy.

        Users can add patterns but cannot remove the system floor.
        If RUN_COMMAND has no TerminalConstraints, one is created
        with just the system patterns. If it already has constraints,
        the system patterns are merged in (deduped, order preserved).
        """
        perm = policy.allowed_actions.get("RUN_COMMAND")
        if perm is None:
            return policy

        system_patterns = list(SYSTEM_TERMINAL_BLOCKED_PATTERNS)

        if perm.constraints is None:
            merged_constraints: dict = {"blocked_patterns": system_patterns}
        elif isinstance(perm.constraints, dict):
            existing = list(perm.constraints.get("blocked_patterns") or [])
            merged = list(dict.fromkeys(system_patterns + existing))
            merged_constraints = {**perm.constraints, "blocked_patterns": merged}
        else:
            return policy

        updated_perm = ActionPermission(safe=perm.safe, constraints=merged_constraints)
        updated_actions = dict(policy.allowed_actions)
        updated_actions["RUN_COMMAND"] = updated_perm

        return _clone_policy(policy, allowed_actions=updated_actions)

    async def _resolve_sources(self, policy: UserPolicy) -> UserPolicy:
        """Walk allowed_actions and resolve any source-backed constraints."""
        updated_actions: dict[str, ActionPermission] = {}
        changed = False

        for action, perm in policy.allowed_actions.items():
            constraints = perm.constraints
            if constraints is None:
                updated_actions[action] = perm
                continue

            if isinstance(constraints, dict) and constraints.get("recipient_sources"):
                resolved = await self._contacts_client.resolve_sources(
                    constraints["recipient_sources"]
                )
                merged = list(
                    set(constraints.get("allowed_recipients") or []) | set(resolved)
                )
                new_constraints = {
                    **constraints,
                    "allowed_recipients": merged,
                    "recipient_sources": [],
                }
                updated_actions[action] = ActionPermission(
                    safe=perm.safe, constraints=new_constraints
                )
                changed = True
            elif isinstance(constraints, dict) and constraints.get("contact_sources"):
                resolved = await self._contacts_client.resolve_sources(
                    constraints["contact_sources"]
                )
                merged = list(
                    set(constraints.get("allowed_contacts") or []) | set(resolved)
                )
                new_constraints = {
                    **constraints,
                    "allowed_contacts": merged,
                    "contact_sources": [],
                }
                updated_actions[action] = ActionPermission(
                    safe=perm.safe, constraints=new_constraints
                )
                changed = True
            else:
                updated_actions[action] = perm

        if not changed:
            return policy

        return _clone_policy(policy, allowed_actions=updated_actions)

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

    # ── Recipient / Source Management ──────────────────────────────────

    def _update_action_constraints(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        new_constraints,
    ) -> None:
        """Replace constraints for a single action in the (user, agent) policy."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None:
            raise KeyError(
                f"Action '{action}' not in policy for user={user_id!r} agent={agent_id!r}"
            )

        updated_perm = ActionPermission(safe=perm.safe, constraints=new_constraints)
        updated_actions = dict(policy.allowed_actions)
        updated_actions[action] = updated_perm

        self._policies[(user_id, agent_id)] = _clone_policy(
            policy, allowed_actions=updated_actions
        )

    def patch_email_recipients(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> EmailConstraints:
        """Add or remove explicit email recipients."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, dict):
            raise KeyError(f"No EmailConstraints found for {action}")

        constraints = EmailConstraints.model_validate(perm.constraints)
        current = list(constraints.allowed_recipients)
        if add:
            current.extend(r for r in add if r not in current)
        if remove:
            current = [r for r in current if r not in remove]

        new_constraints = EmailConstraints(
            allowed_recipients=current,
            recipient_sources=list(constraints.recipient_sources),
        )
        new_dict = new_constraints.model_dump(mode="python")
        self._update_action_constraints(user_id, agent_id, action, new_dict)
        return new_constraints

    def add_email_source(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        source: RecipientSource,
    ) -> EmailConstraints:
        """Add a recipient source rule to email constraints."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, dict):
            raise KeyError(f"No EmailConstraints found for {action}")

        constraints = EmailConstraints.model_validate(perm.constraints)
        sources = list(constraints.recipient_sources) + [source]
        new_constraints = EmailConstraints(
            allowed_recipients=list(constraints.allowed_recipients),
            recipient_sources=sources,
        )
        new_dict = new_constraints.model_dump(mode="python")
        self._update_action_constraints(user_id, agent_id, action, new_dict)
        return new_constraints

    def remove_email_source(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        source_type: str,
        source_filter: str = "",
    ) -> EmailConstraints:
        """Remove a recipient source by type and filter."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, dict):
            raise KeyError(f"No EmailConstraints found for {action}")

        constraints = EmailConstraints.model_validate(perm.constraints)
        sources = [
            s for s in constraints.recipient_sources
            if not (s.source == source_type and s.filter == source_filter)
        ]
        new_constraints = EmailConstraints(
            allowed_recipients=list(constraints.allowed_recipients),
            recipient_sources=sources,
        )
        new_dict = new_constraints.model_dump(mode="python")
        self._update_action_constraints(user_id, agent_id, action, new_dict)
        return new_constraints

    def patch_message_contacts(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> MessageConstraints:
        """Add or remove explicit message contacts."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, dict):
            raise KeyError(f"No MessageConstraints found for {action}")

        constraints = MessageConstraints.model_validate(perm.constraints)
        current = list(constraints.allowed_contacts)
        if add:
            current.extend(c for c in add if c not in current)
        if remove:
            current = [c for c in current if c not in remove]

        new_constraints = MessageConstraints(
            allowed_contacts=current,
            contact_sources=list(constraints.contact_sources),
        )
        new_dict = new_constraints.model_dump(mode="python")
        self._update_action_constraints(user_id, agent_id, action, new_dict)
        return new_constraints

    def add_message_source(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        source: ContactSource,
    ) -> MessageConstraints:
        """Add a contact source rule to message constraints."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, dict):
            raise KeyError(f"No MessageConstraints found for {action}")

        constraints = MessageConstraints.model_validate(perm.constraints)
        sources = list(constraints.contact_sources) + [source]
        new_constraints = MessageConstraints(
            allowed_contacts=list(constraints.allowed_contacts),
            contact_sources=sources,
        )
        new_dict = new_constraints.model_dump(mode="python")
        self._update_action_constraints(user_id, agent_id, action, new_dict)
        return new_constraints

    def remove_message_source(
        self,
        user_id: str,
        agent_id: str,
        action: str,
        source_type: str,
        source_filter: str = "",
    ) -> MessageConstraints:
        """Remove a contact source by type and filter."""
        policy = self.get_user_policy(user_id, agent_id)
        perm = policy.allowed_actions.get(action)
        if perm is None or not isinstance(perm.constraints, dict):
            raise KeyError(f"No MessageConstraints found for {action}")

        constraints = MessageConstraints.model_validate(perm.constraints)
        sources = [
            s for s in constraints.contact_sources
            if not (s.source == source_type and s.filter == source_filter)
        ]
        new_constraints = MessageConstraints(
            allowed_contacts=list(constraints.allowed_contacts),
            contact_sources=sources,
        )
        new_dict = new_constraints.model_dump(mode="python")
        self._update_action_constraints(user_id, agent_id, action, new_dict)
        return new_constraints
