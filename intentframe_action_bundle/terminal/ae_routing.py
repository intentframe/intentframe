"""Terminal bundle — AE prompt id selection for RUN_COMMAND."""

from __future__ import annotations

from intentframe_core.types import CommandIntel, FileIntel, IntentFrame

from intentframe_action_bundle.terminal import ACTION_IDS
from intentframe_action_bundle.terminal.prompt_routing import (
    has_network_mutation,
    has_network_probe,
)


def select_ae_prompt_id(
    intent: IntentFrame,
    command_intel: CommandIntel | None,
    file_intel: FileIntel | None = None,
) -> str | None:
    if intent.action.value not in ACTION_IDS:
        return None

    caps = command_intel.capabilities if command_intel else ()
    if has_network_mutation(caps):
        return "critical_network_mutation"
    if has_network_probe(caps):
        return "critical_network_probe"
    return "critical_run_command"
