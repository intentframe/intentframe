"""Files bundle deterministic gates."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.shared.files.path_heuristics import is_sensitive_write_path
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome


def decide_write_file_sensitive_path(
    intent: IntentFrame,
    ctx: BundleContext,
) -> BundlePhaseOutcome | None:
    if intent.action != ActionType.WRITE_FILE.value:
        return None
    # ``data["path"]`` is the executed resource (same field the adapter acts
    # on). ``intent.target`` is display/audit only.
    path = (intent.data or {}).get("path", "")
    if not is_sensitive_write_path(path):
        return None
    return BundlePhaseOutcome.block(
        ctx,
        reason=(
            f"Write to sensitive system location is not permitted: "
            f"{path!r}"
        ),
        matched_gate="write_file_sensitive_path",
    )
