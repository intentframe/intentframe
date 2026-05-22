"""Per-constraint-type summaries for onboarding prompts."""

from __future__ import annotations

from intentframe_action_bundle.onboarding.action_groups import OUTBOUND_EMAIL_ACTIONS
from intentframe_action_bundle.onboarding.deny_capabilities import summarize_deny_capabilities
from policy_registry.constraints.email import EmailConstraints
from policy_registry.constraints.file import FileConstraints
from policy_registry.constraints.host_file import HostFileConstraints
from policy_registry.constraints.message import MessageConstraints
from policy_registry.constraints.terminal import TerminalConstraints
from policy_registry.models import ConstraintTypes


def summarize_constraints_for_onboarding(action: str, constraints: ConstraintTypes) -> str:
    """Conceptual constraint brief for the onboarding meta-LLM."""
    if isinstance(constraints, EmailConstraints):
        if action in OUTBOUND_EMAIL_ACTIONS:
            return (
                "outbound email recipients must come from the user's "
                "contact list or configured recipient allowlist"
            )
        return "email recipient constraints are configured"

    if isinstance(constraints, MessageConstraints):
        return "message recipients must come from the user's contact list"

    if isinstance(constraints, FileConstraints):
        allowed = ", ".join(repr(path) for path in constraints.allowed_paths)
        if allowed:
            return (
                "file operations must stay within these allowed paths: "
                f"[{allowed}]"
            )
        return "file operations are constrained by configured allowed paths"

    if isinstance(constraints, HostFileConstraints):
        allowed = ", ".join(repr(path) for path in constraints.allowed_host_paths)
        if allowed:
            return (
                "host file operations must stay within these allowed host "
                f"paths: [{allowed}]"
            )
        return (
            "host file operations are constrained by configured allowed "
            "host paths"
        )

    if isinstance(constraints, TerminalConstraints):
        blocked = ", ".join(repr(pattern) for pattern in constraints.blocked_patterns)
        allowed = ", ".join(repr(cmd) for cmd in constraints.allowed_commands)
        deny_caps = constraints.deny_capabilities or frozenset()
        parts: list[str] = []
        if blocked:
            parts.append(f"blocked patterns: [{blocked}]")
        if allowed:
            parts.append(f"allowed commands: [{allowed}]")
        if deny_caps:
            parts.append(summarize_deny_capabilities(deny_caps))
        if parts:
            return "; ".join(parts)
        return "terminal command constraints are configured"

    return constraints.model_dump_json()
