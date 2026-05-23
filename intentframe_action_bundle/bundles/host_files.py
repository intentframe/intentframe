"""Host files action bundle."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.evidence import FileIntel
from intentframe_action_bundle.files.ai_context import (
    render_file_external_context,
    select_write_file_ae_system_instructions,
)
from intentframe_action_bundle.files.evidence_keys import FILE_INTEL_KEY
from intentframe_action_bundle.files.pre_pipeline import run_files_pre_pipeline
from intentframe_action_bundle.host_files.deterministic import (
    HOST_FILE_ACTIONS,
    decide_host_file_floor,
)
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext, BundlePhaseOutcome
from intentframe_action_bundle.types import BundleGateDecision
from policy_registry.constraints.host_file import HostFileConstraints


class HostFilesActionBundle(ActionBundle):
    bundle_id = "host_files"
    action_ids = HOST_FILE_ACTIONS
    constraint_type = HostFileConstraints

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del permission
        if intent.action.value == ActionType.WRITE_HOST_FILE.value:
            ctx.evidence[FILE_INTEL_KEY] = run_files_pre_pipeline(intent, verbose=verbose)
        return BundlePhaseOutcome.continue_(ctx)

    def structural_gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        del permission
        gate = decide_host_file_floor(intent)
        if gate is None:
            return BundlePhaseOutcome.continue_(ctx)
        if gate.decision is BundleGateDecision.BLOCK:
            return BundlePhaseOutcome.block(
                ctx,
                reason=gate.reason,
                matched_gate=gate.matched_gate,
            )
        return BundlePhaseOutcome.continue_(ctx)

    def build_ai_context(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        del permission
        if intent.action.value != ActionType.WRITE_HOST_FILE.value:
            return BundleAIContext()
        file_intel = ctx.evidence.get(FILE_INTEL_KEY)
        if file_intel is not None and not isinstance(file_intel, FileIntel):
            file_intel = None
        system, label = select_write_file_ae_system_instructions()
        return BundleAIContext(
            ae_system_instructions=system,
            ae_external_context=render_file_external_context(file_intel),
            ae_prompt_label=label,
        )
