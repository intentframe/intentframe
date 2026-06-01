"""Onboarding middle block for terminal actions."""

from __future__ import annotations

from intentframe_native_kit.action_registry.types import ActionType


def terminal_onboarding_guardrails() -> str:
    run_command = ActionType.RUN_COMMAND.value
    return f"""### Terminal ({run_command})
- HIGH RISK - always flag as warning.
- Specify allowed command patterns from constraints.
- Require confirmation for destructive operations.
- If u have deny_capabilities, you must include a guardrail to how to use the {run_command.lower()} action."""
