"""Action bundle registry — run family deterministic gates."""

from __future__ import annotations

from intentframe_core.types import IntentFrame

from intentframe_action_bundle.types import (
    BundleDeterministicContext,
    BundleGateDecision,
    BundleGateResult,
)


def resolve_bundle(action_value: str) -> str | None:
    from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
    from intentframe_action_bundle.host_files.deterministic import HOST_FILE_ACTIONS
    from intentframe_action_bundle.passive_read.actions import PASSIVE_READ_ACTIONS
    from intentframe_action_bundle.terminal import ACTION_IDS as TERMINAL_ACTIONS

    if action_value in TERMINAL_ACTIONS:
        return "terminal"
    if action_value in WRITE_FILE_ACTIONS:
        return "files"
    if action_value in HOST_FILE_ACTIONS:
        return "host_files"
    if action_value in PASSIVE_READ_ACTIONS:
        return "passive_read"
    return None


def _to_deterministic_result(gate: BundleGateResult):
    from intentframe_components.guardian.deterministic import (
        DeterministicDecision,
        DeterministicResult,
    )

    decision = (
        DeterministicDecision.BLOCK
        if gate.decision is BundleGateDecision.BLOCK
        else DeterministicDecision.ALLOW
    )
    return DeterministicResult(
        decision=decision,
        reason=gate.reason,
        matched_gate=gate.matched_gate,
    )


def run_bundle_deterministic(
    intent: IntentFrame,
    permission,
    ctx: BundleDeterministicContext,
):
    from intentframe_action_bundle.files.deterministic import (
        decide_write_file_sensitive_path,
    )
    from intentframe_action_bundle.host_files.deterministic import decide_host_file_floor
    from intentframe_action_bundle.passive_read.deterministic import decide_passive_read
    from intentframe_action_bundle.terminal.deterministic import decide_run_command

    for gate_fn in (
        lambda: decide_write_file_sensitive_path(intent),
        lambda: decide_host_file_floor(intent),
        lambda: decide_passive_read(intent, permission),
        lambda: decide_run_command(intent, permission, ctx.command_intel),
    ):
        gate = gate_fn()
        if gate is not None:
            return _to_deterministic_result(gate)
    return None
