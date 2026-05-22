"""Files bundle deterministic gates."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.types import BundleGateDecision, BundleGateResult


def decide_write_file_sensitive_path(intent: IntentFrame) -> BundleGateResult | None:
    from intentframe_components.heuristics import is_sensitive_write_path

    if intent.action.value != ActionType.WRITE_FILE.value:
        return None
    if not is_sensitive_write_path(intent.target):
        return None
    return BundleGateResult(
        decision=BundleGateDecision.BLOCK,
        reason=(
            f"Write to sensitive system location is not permitted: "
            f"{intent.target!r}"
        ),
        matched_gate="write_file_sensitive_path",
    )
