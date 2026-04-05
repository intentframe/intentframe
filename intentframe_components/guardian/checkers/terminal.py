"""Constraint checker for TERMINAL category actions."""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import ConstraintChecker
from policy_registry.constraints.terminal import TerminalConstraints


class TerminalChecker(ConstraintChecker):
    """Command-pattern constraint enforcement for terminal operations.

    Evaluation order:
        1. Blocklist (substring match) — reject if any blocked pattern found.
        2. Allowlist (glob match) — if non-empty, command must match at least one.
    """

    def check(self, intent: IntentFrame, constraints: TerminalConstraints) -> tuple[bool, str]:
        command = intent.target or (intent.data or {}).get("command", "")

        for pattern in constraints.blocked_patterns:
            if pattern in command:
                return False, f"Command blocked — matched pattern: {pattern}"

        if constraints.allowed_commands:
            for pattern in constraints.allowed_commands:
                if fnmatch.fnmatch(command, pattern):
                    return True, ""
            return False, f"Command '{command}' not in allowed commands"

        return True, ""

    def summarize(self, constraints: TerminalConstraints) -> str:
        parts: list[str] = []
        if constraints.blocked_patterns:
            parts.append(f"Blocked patterns: {', '.join(constraints.blocked_patterns)}")
        if constraints.allowed_commands:
            parts.append(f"Allowed commands: {', '.join(constraints.allowed_commands)}")
        return "; ".join(parts) if parts else "No terminal constraints"
