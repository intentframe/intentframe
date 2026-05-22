"""Files bundle — AE prompt id selection for WRITE_FILE-family actions."""

from __future__ import annotations

from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
from intentframe_bundle_sdk.types import BundleContext


def select_ae_prompt_id(ctx: BundleContext) -> str | None:
    if ctx.effective_intent.action.value in WRITE_FILE_ACTIONS:
        return "critical_write_file"
    return None
