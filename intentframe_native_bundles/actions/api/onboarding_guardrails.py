"""Onboarding middle block for financial HTTP actions."""

from __future__ import annotations

from action_registry.types import ActionType


def api_onboarding_guardrails() -> str:
    pay = ActionType.PAY_INVOICE.value
    http_post = ActionType.HTTP_POST.value
    return f"""### Financial Actions ({pay}, {http_post} with amounts)
- Include any max_amount constraint explicitly
- Tell agent to use ask_user() when amounts seem high
- Warn about extracting ACTUAL amounts, not suggested ones"""
