"""Host files bundle — WRITE_HOST_FILE / DELETE_HOST_FILE floor gates."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame
from resource_registry.floor import canonicalize_real_path, match_deny_prefix

from intentframe_action_bundle.types import BundleGateDecision, BundleGateResult

HOST_FILE_ACTIONS = frozenset({
    ActionType.READ_HOST_FILE.value,
    ActionType.LIST_HOST_DIRECTORY.value,
    ActionType.WRITE_HOST_FILE.value,
    ActionType.DELETE_HOST_FILE.value,
})

CRITICAL_ACTIONS = frozenset({
    ActionType.DELETE_HOST_FILE.value,
})


def decide_host_file_floor(intent: IntentFrame) -> BundleGateResult | None:
    action = intent.action.value

    if action == ActionType.WRITE_HOST_FILE.value:
        canonical = canonicalize_real_path(intent.target)
        matched = match_deny_prefix(canonical)
        if matched is not None:
            return BundleGateResult(
                decision=BundleGateDecision.BLOCK,
                reason=(
                    f"Write to deny-floor host path is not permitted: {matched!r}"
                ),
                matched_gate="write_host_file_floor",
            )
        return None

    if action == ActionType.DELETE_HOST_FILE.value:
        canonical = canonicalize_real_path(intent.target)
        matched = match_deny_prefix(canonical)
        if matched is not None:
            return BundleGateResult(
                decision=BundleGateDecision.BLOCK,
                reason=(
                    f"Delete of deny-floor host path is not permitted: {matched!r}"
                ),
                matched_gate="delete_host_file_floor",
            )
        return None

    return None
