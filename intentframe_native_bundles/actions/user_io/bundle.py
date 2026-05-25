"""User interaction action bundle — ASK_USER and UI prompt actions."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle
from intentframe_native_bundles.actions.user_io.onboarding_guardrails import (
    user_io_onboarding_guardrails,
)


class UserIoActionBundle(ActionBundle):
    bundle_id = "user_io"
    action_ids = frozenset({
        ActionType.ASK_USER.value,
        ActionType.SHOW_MESSAGE.value,
        ActionType.GET_CONFIRMATION.value,
        "SHOW_OPTIONS",
        ActionType.SHOW_NOTIFICATION.value,
    })

    def onboarding_guardrails(self) -> str:
        return user_io_onboarding_guardrails()
