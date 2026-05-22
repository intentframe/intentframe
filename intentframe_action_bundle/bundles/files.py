"""Files action bundle — WRITE_FILE family."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
from intentframe_action_bundle.files.deterministic import decide_write_file_sensitive_path
from intentframe_action_bundle.files.pre_pipeline import run_files_pre_pipeline
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome
from intentframe_action_bundle.types import BundleGateDecision


class FilesActionBundle(ActionBundle):
    bundle_id = "files"
    action_ids = frozenset({ActionType.WRITE_FILE.value})
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
        ctx.file_intel = run_files_pre_pipeline(intent, verbose=verbose)
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
