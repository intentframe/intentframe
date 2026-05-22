"""Constraint checker for TERMINAL category actions."""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker
from policy_registry.constraints._capability_match import (
    any_tag_matches,
    matches_any,
)
from policy_registry.constraints.terminal import TerminalConstraints


class TerminalChecker(ConstraintChecker):
    """Command-pattern constraint enforcement for terminal operations.

    Evaluation order (first BLOCK wins):

        1. Blocklist substring  — reject if any blocked_patterns substring
           appears in the raw command.
        2. deny_capabilities    — reject if any tag on the command's
           CommandIntel matches a deny pattern.
        3. Allowlist glob       — if allowed_commands is non-empty, the
           raw command must match at least one glob.
        4. allow_capabilities   — if non-empty, EVERY capability tag on
           the command must be explicitly covered by an allow pattern.
           An unknown tag is treated as outside the policy surface and
           BLOCKed (fail-closed).

    ``command_intel`` is read from ``context.command_intel`` when
    present.  When absent (None) capability checks are skipped — the
    pipeline only populates it for RUN_COMMAND, so any caller that
    routes a non-terminal action through this checker (shouldn't
    happen; defensive) simply runs the substring/glob path.
    """

    def check(
        self,
        intent: IntentFrame,
        constraints: TerminalConstraints,
        context: CheckContext | None = None,
    ) -> tuple[bool, str]:
        command = intent.target or (intent.data or {}).get("command", "")

        for pattern in constraints.blocked_patterns:
            if pattern in command:
                return False, f"Command blocked — matched pattern: {pattern}"

        command_intel = context.command_intel if context else None
        capabilities: tuple[str, ...] = (
            command_intel.capabilities if command_intel is not None else ()
        )

        if constraints.deny_capabilities and capabilities:
            hit = any_tag_matches(capabilities, constraints.deny_capabilities)
            if hit is not None:
                return (
                    False,
                    f"Command blocked — capability '{hit}' denied by policy",
                )

        if constraints.allowed_commands:
            matched_allowlist = any(
                fnmatch.fnmatch(command, pattern)
                for pattern in constraints.allowed_commands
            )
            if not matched_allowlist:
                return False, f"Command '{command}' not in allowed commands"

        if constraints.allow_capabilities and capabilities:
            for tag in capabilities:
                if not matches_any(tag, constraints.allow_capabilities):
                    return (
                        False,
                        f"Command blocked — capability '{tag}' not in "
                        f"allowed capabilities",
                    )

        return True, ""

    def summarize(self, constraints: TerminalConstraints) -> str:
        parts: list[str] = []
        if constraints.blocked_patterns:
            parts.append(f"Blocked patterns: {', '.join(constraints.blocked_patterns)}")
        if constraints.allowed_commands:
            parts.append(f"Allowed commands: {', '.join(constraints.allowed_commands)}")
        if constraints.deny_capabilities:
            parts.append(
                f"Deny capabilities: {', '.join(sorted(constraints.deny_capabilities))}"
            )
        if constraints.allow_capabilities:
            parts.append(
                f"Allow capabilities: {', '.join(sorted(constraints.allow_capabilities))}"
            )
        return "; ".join(parts) if parts else "No terminal constraints"
