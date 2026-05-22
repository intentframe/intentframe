"""Passive read action bundle."""

from __future__ import annotations

from intentframe_core.types import IntentFrame

from intentframe_action_bundle.passive_read.actions import PASSIVE_READ_ACTIONS
from intentframe_action_bundle.passive_read.deterministic import decide_passive_read
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome
from intentframe_action_bundle.types import BundleGateDecision
from policy_registry.constraints.file import FileConstraints


class PassiveReadActionBundle(ActionBundle):
    bundle_id = "passive_read"
    action_ids = PASSIVE_READ_ACTIONS
    constraint_type = FileConstraints

    async def enrich(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del permission, verbose
        from intentframe_action_bundle.email.enrich import (
            EMAIL_MESSAGE_ACTIONS,
            enrich_intent,
        )

        if intent.action.value in EMAIL_MESSAGE_ACTIONS:
            ctx.enriched_intent = await enrich_intent(intent)
        return BundlePhaseOutcome.continue_(ctx)

    def allow_gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        gate = decide_passive_read(intent, permission)
        if gate is None:
            return BundlePhaseOutcome.continue_(ctx)
        if gate.decision is BundleGateDecision.ALLOW:
            return BundlePhaseOutcome.allow(
                ctx,
                reason=gate.reason,
                matched_gate=gate.matched_gate,
            )
        return BundlePhaseOutcome.continue_(ctx)
