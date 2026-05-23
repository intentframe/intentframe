"""Terminal action bundle — RUN_COMMAND."""

from __future__ import annotations

from intentframe_core.types import IntentFrame
from policy_registry.constraints.terminal import TerminalConstraints

from intentframe_action_bundle.evidence import CommandIntel
from intentframe_action_bundle.terminal import ACTION_IDS
from intentframe_action_bundle.terminal._read_only import is_read_only_fast_path
from intentframe_action_bundle.terminal.ai_context import (
    render_terminal_external_context,
    select_terminal_ae_system_instructions,
)
from intentframe_action_bundle.terminal.evidence_keys import (
    COMMAND_INTEL_KEY,
    TERMINAL_COMMAND_SIGNALS_KEY,
)
from intentframe_action_bundle.terminal.pre_pipeline import run_terminal_pre_pipeline
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext, BundlePhaseOutcome


class TerminalActionBundle(ActionBundle):
    bundle_id = "terminal"
    action_ids = ACTION_IDS
    constraint_type = TerminalConstraints

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del permission
        (
            command_intel,
            terminal_command_signals,
            early_block,
            audit_entry,
        ) = run_terminal_pre_pipeline(intent, verbose=verbose)

        if early_block is not None:
            del audit_entry
            block_data = early_block.data or {}
            reason = block_data.get("reason") or early_block.error or "catastrophic command detected"
            if str(reason).startswith("Blocked by command_shield: "):
                reason = str(reason)[len("Blocked by command_shield: ") :]
            return BundlePhaseOutcome.block(
                ctx,
                reason=str(reason),
                matched_gate="command_shield",
            )

        ctx.evidence[COMMAND_INTEL_KEY] = command_intel
        ctx.evidence[TERMINAL_COMMAND_SIGNALS_KEY] = terminal_command_signals
        return BundlePhaseOutcome.continue_(ctx)

    def allow_gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        if intent.action.value not in self.action_ids:
            return BundlePhaseOutcome.continue_(ctx)
        command_intel = ctx.evidence.get(COMMAND_INTEL_KEY)
        if command_intel is None:
            return BundlePhaseOutcome.continue_(ctx)

        deny_caps = self._deny_capabilities(permission.constraints)
        if is_read_only_fast_path(command_intel, deny_caps):
            return BundlePhaseOutcome.allow(
                ctx,
                reason="Permitted (deterministic: read-only command)",
                matched_gate="run_command_read_only",
            )
        return BundlePhaseOutcome.continue_(ctx)

    def build_ai_context(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        del intent, permission
        command_intel = ctx.evidence.get(COMMAND_INTEL_KEY)
        if command_intel is not None and not isinstance(command_intel, CommandIntel):
            command_intel = None
        signals = ctx.evidence.get(TERMINAL_COMMAND_SIGNALS_KEY, ())
        if not isinstance(signals, tuple):
            signals = ()
        system, label = select_terminal_ae_system_instructions(command_intel)
        return BundleAIContext(
            ae_system_instructions=system,
            ae_external_context=render_terminal_external_context(signals),
            ae_prompt_label=label,
            extras={"terminal_command_signals": signals},
        )

    @staticmethod
    def _deny_capabilities(constraints) -> frozenset[str]:
        if isinstance(constraints, TerminalConstraints):
            return constraints.deny_capabilities
        return frozenset()
