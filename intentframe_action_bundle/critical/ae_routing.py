"""Critical bundle — AE prompt id for CRITICAL_ACTIONS (generic lane)."""

from __future__ import annotations

from intentframe_core.types import CommandIntel, FileIntel, IntentFrame

from intentframe_action_bundle.taxonomy import is_critical


def select_ae_prompt_id(
    intent: IntentFrame,
    command_intel: CommandIntel | None,
    file_intel: FileIntel | None = None,
) -> str | None:
    del command_intel, file_intel
    if is_critical(intent.action.value):
        return "critical_generic"
    return None
