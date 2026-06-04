"""Onboarding middle block for user interaction actions."""

from __future__ import annotations

from intentframe_native_kit.action_registry.types import ActionType


def user_io_onboarding_guardrails() -> str:
    ask_user = ActionType.ASK_USER.value
    return f"""### User Interaction ({ask_user})
- Keep questions clear and necessary
- Don't ask for sensitive information"""
