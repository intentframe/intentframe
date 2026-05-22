"""Critical bundle — AE prompt id for CRITICAL_ACTIONS (generic lane)."""

from __future__ import annotations

from intentframe_action_bundle.taxonomy import is_critical
from intentframe_bundle_sdk.types import BundleContext


def select_ae_prompt_id(ctx: BundleContext) -> str | None:
    if is_critical(ctx.effective_intent.action.value):
        return "critical_generic"
    return None
