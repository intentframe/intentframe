"""Constraint checker for EMAIL category actions.

Runs for SEND_EMAIL, REPLY_EMAIL, and FORWARD_EMAIL (the outbound
actions that seed_policies assigns an EmailConstraints to).

Recipient location per action:
  SEND_EMAIL    → data["to"]         (set by agent directly)
  FORWARD_EMAIL → data["to"]         (set by agent directly)
  REPLY_EMAIL   → data["to"]         (set by email enricher from original sender)
"""

from __future__ import annotations

import fnmatch
import re

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker
from policy_registry.constraints.email import EmailConstraints

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

_ENRICHER_RESOLVED = frozenset({ActionType.REPLY_EMAIL.value})


class EmailChecker(ConstraintChecker):
    """Recipient-based constraint enforcement for email operations."""

    @staticmethod
    def _extract_emails(value: str) -> list[str]:
        """Extract all email addresses from a value that may contain
        display names, comma-separated lists, etc."""
        return _EMAIL_RE.findall(value)

    def check(
        self,
        intent: IntentFrame,
        constraints: EmailConstraints,
        context: CheckContext | None = None,
    ) -> tuple[bool, str]:
        del context
        data = intent.data or {}
        action = intent.action.value

        raw_to = str(data.get("to", "")).strip()

        recipients = self._extract_emails(raw_to) if raw_to else []
        if not recipients:
            if action in _ENRICHER_RESOLVED:
                return False, (
                    "Could not determine reply recipient — email enrichment "
                    "likely failed (bad or hallucinated rfc_message_id?)"
                )
            return False, "No recipient email address specified"

        for addr in recipients:
            if not any(fnmatch.fnmatch(addr, pat) for pat in constraints.allowed_recipients):
                return False, f"Recipient '{addr}' not in allowed recipients"

        return True, ""

    def summarize(self, constraints: EmailConstraints) -> str:
        recipients = constraints.allowed_recipients
        if len(recipients) <= 10:
            return f"Allowed recipients: {', '.join(recipients)}"
        return f"Allowed recipients: {len(recipients)} addresses configured"
