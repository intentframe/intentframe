"""Files bundle — AE prompt id selection for WRITE_FILE-family actions."""

from __future__ import annotations

from intentframe_core.types import CommandIntel, FileIntel, IntentFrame

from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS


def select_ae_prompt_id(
    intent: IntentFrame,
    command_intel: CommandIntel | None,
    file_intel: FileIntel | None = None,
) -> str | None:
    del command_intel, file_intel
    if intent.action.value in WRITE_FILE_ACTIONS:
        return "critical_write_file"
    return None
