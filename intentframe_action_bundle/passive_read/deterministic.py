"""Passive-read bundle — deterministic ALLOW for safe read actions."""

from __future__ import annotations

from intentframe_core.types import IntentFrame

from intentframe_action_bundle.passive_read.actions import PASSIVE_READ_ACTIONS
from intentframe_action_bundle.types import BundleGateDecision, BundleGateResult


def decide_passive_read(intent: IntentFrame, permission) -> BundleGateResult | None:
    action = intent.action.value
    if action not in PASSIVE_READ_ACTIONS:
        return None
    if not permission.safe:
        return None
    return BundleGateResult(
        decision=BundleGateDecision.ALLOW,
        reason=f"Permitted (deterministic: passive read): {action}",
        matched_gate="passive_read",
    )
