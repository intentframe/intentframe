"""Email action bundle — enrich + checker for outbound / mutating email."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.email.enrich import EMAIL_MESSAGE_ACTIONS, enrich_intent
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome
from policy_registry.constraints.email import EmailConstraints

_EMAIL_BUNDLE_ACTIONS: frozenset[str] = frozenset(
    {
        ActionType.SEND_EMAIL.value,
        ActionType.REPLY_EMAIL.value,
        ActionType.FORWARD_EMAIL.value,
        ActionType.MARK_READ_EMAIL.value,
        ActionType.MOVE_EMAIL.value,
        ActionType.DELETE_EMAIL.value,
    }
)


class EmailActionBundle(ActionBundle):
    bundle_id = "email"
    action_ids = _EMAIL_BUNDLE_ACTIONS
    constraint_type = EmailConstraints

    async def enrich(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del permission, verbose
        if intent.action.value in EMAIL_MESSAGE_ACTIONS:
            ctx.enriched_intent = await enrich_intent(intent)
        return BundlePhaseOutcome.continue_(ctx)
