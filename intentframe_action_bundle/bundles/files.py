"""Files action bundle — virtual filesystem family.

Registers VFS file action ids and wires hooks to ``intentframe_action_bundle.files``.
See ``files/__init__.py`` for the shared write-tooling ownership rule.
"""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.evidence import FileIntel
from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
from intentframe_action_bundle.files.ai_context import (
    render_file_external_context,
    select_write_file_ae_system_instructions,
)
from intentframe_action_bundle.files.deterministic import decide_write_file_sensitive_path
from intentframe_action_bundle.files.evidence_keys import FILE_INTEL_KEY
from intentframe_action_bundle.files.pre_pipeline import run_files_pre_pipeline
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext, BundlePhaseOutcome
from intentframe_action_bundle.types import BundleGateDecision


class FilesActionBundle(ActionBundle):
    bundle_id = "files"
    action_ids = frozenset({
        ActionType.WRITE_FILE.value,
        ActionType.READ_FILE.value,
        ActionType.LIST_DIRECTORY.value,
        ActionType.APPEND_ROW.value,
        ActionType.DELETE_FILE.value,
    })
    passive_read_action_ids = frozenset({
        ActionType.READ_FILE.value,
        ActionType.LIST_DIRECTORY.value,
    })
    constraint_type = None  # FileChecker wired via manifest for WRITE_FILE constraints

    def __init__(self) -> None:
        from policy_registry.constraints.file import FileConstraints

        self.constraint_type = FileConstraints

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del permission
        ctx.evidence[FILE_INTEL_KEY] = run_files_pre_pipeline(intent, verbose=verbose)
        return BundlePhaseOutcome.continue_(ctx)

    def structural_gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        del permission
        gate = decide_write_file_sensitive_path(intent)
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
        del intent, permission
        file_intel = ctx.evidence.get(FILE_INTEL_KEY)
        if file_intel is not None and not isinstance(file_intel, FileIntel):
            file_intel = None
        system, label = select_write_file_ae_system_instructions()
        return BundleAIContext(
            ae_system_instructions=system,
            ae_external_context=render_file_external_context(file_intel),
            ae_prompt_label=label,
        )
