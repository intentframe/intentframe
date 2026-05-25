"""Onboarding middle block for outbound email actions."""

from __future__ import annotations

from action_registry.types import ActionType

OUTBOUND_EMAIL_ACTIONS: frozenset[str] = frozenset({
    ActionType.SEND_EMAIL.value,
    ActionType.REPLY_EMAIL.value,
    ActionType.FORWARD_EMAIL.value,
})


def _join_actions(actions: frozenset[str]) -> str:
    return ", ".join(sorted(actions))


def email_onboarding_guardrails() -> str:
    actions = _join_actions(OUTBOUND_EMAIL_ACTIONS)
    return f"""### Email Actions ({actions})
- For outbound email constraints, tell the agent to only send, reply, or forward emails to recipients from the user's contact list or configured allowlist
- Do not list concrete email addresses from resolved policies in the guardrails
- Phrase email rules conceptually (for example: "only send/reply/forward emails to the user's contacts")"""
