"""Terminal bundle deterministic gates — RUN_COMMAND read-only fast path."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_action_bundle.evidence import CommandIntel
from intentframe_core.types import IntentFrame
from policy_registry.constraints.terminal import TerminalConstraints

from intentframe_action_bundle.terminal._read_only import is_read_only_fast_path
from intentframe_action_bundle.types import BundleGateDecision, BundleGateResult


def decide_run_command(
    intent: IntentFrame,
    permission,
    command_intel: CommandIntel | None,
) -> BundleGateResult | None:
    if intent.action.value != ActionType.RUN_COMMAND.value:
        return None
    if command_intel is None:
        return None

    deny_caps = _deny_capabilities(permission.constraints)
    if is_read_only_fast_path(command_intel, deny_caps):
        return BundleGateResult(
            decision=BundleGateDecision.ALLOW,
            reason="Permitted (deterministic: read-only command)",
            matched_gate="run_command_read_only",
        )
    return None


def _deny_capabilities(constraints) -> frozenset[str]:
    if isinstance(constraints, TerminalConstraints):
        return constraints.deny_capabilities
    return frozenset()
