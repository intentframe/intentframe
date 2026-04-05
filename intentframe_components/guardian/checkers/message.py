"""Constraint checker for MESSAGES category actions."""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import ConstraintChecker
from policy_registry.constraints.message import MessageConstraints


class MessageChecker(ConstraintChecker):
    """Contact-based constraint enforcement for messaging operations."""

    def check(self, intent: IntentFrame, constraints: MessageConstraints) -> tuple[bool, str]:
        contact = (intent.data or {}).get("to", intent.target)
        for pattern in constraints.allowed_contacts:
            if fnmatch.fnmatch(str(contact), pattern):
                return True, ""
        return False, f"Contact '{contact}' not in allowed contacts"

    def summarize(self, constraints: MessageConstraints) -> str:
        contacts = constraints.allowed_contacts
        if len(contacts) <= 10:
            return f"Allowed contacts: {', '.join(contacts)}"
        return f"Allowed contacts: {len(contacts)} contacts configured"
