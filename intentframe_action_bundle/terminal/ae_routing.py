"""Terminal bundle — AE prompt id selection for RUN_COMMAND."""

from __future__ import annotations

from intentframe_action_bundle.terminal import ACTION_IDS
from intentframe_action_bundle.terminal.prompt_routing import (
    has_network_mutation,
    has_network_probe,
)
from intentframe_bundle_sdk.types import BundleContext


def select_ae_prompt_id(ctx: BundleContext) -> str | None:
    intent = ctx.effective_intent
    if intent.action.value not in ACTION_IDS:
        return None

    caps = ctx.command_intel.capabilities if ctx.command_intel else ()
    if has_network_mutation(caps):
        return "critical_network_mutation"
    if has_network_probe(caps):
        return "critical_network_probe"
    return "critical_run_command"
