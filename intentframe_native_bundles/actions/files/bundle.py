"""Files action bundle — virtual filesystem family."""

from __future__ import annotations

import fnmatch

from action_registry.types import ActionType
from intentframe_core.paths import normalize_virtual_path
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.actions.files.ai_context import (
    render_file_external_context,
    select_write_file_ae_system_instructions,
)
from intentframe_native_bundles.actions.files.constraints import FileConstraints
from intentframe_native_bundles.actions.files.deterministic import decide_write_file_sensitive_path
from intentframe_native_bundles.actions.files.evidence import FileIntel
from intentframe_native_bundles.actions.files.evidence_keys import FILE_INTEL_KEY
from intentframe_native_bundles.actions.files.pre_pipeline import run_files_pre_pipeline
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleAIContext,
    BundleContext,
    BundlePhaseOutcome,
)


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

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        ctx.evidence[FILE_INTEL_KEY] = run_files_pre_pipeline(intent, verbose=verbose)
        return BundlePhaseOutcome.continue_(ctx)

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            FileConstraints.model_validate(action_permission.constraints)

    def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del verbose
        if action_permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = FileConstraints.model_validate(action_permission.constraints)
        if not self._path_matches(intent.target, constraints.allowed_paths):
            return BundlePhaseOutcome.block(
                ctx,
                reason=f"Constraint violation: Path '{intent.target}' not in allowed paths",
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = FileConstraints.model_validate(action_permission.constraints)
        return f"Allowed paths: {', '.join(constraints.allowed_paths)}"

    def structural_gates(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        outcome = decide_write_file_sensitive_path(intent, ctx)
        if outcome is None:
            return BundlePhaseOutcome.continue_(ctx)
        return outcome

    def build_ai_context(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        del intent, action_permission
        file_intel = ctx.evidence.get(FILE_INTEL_KEY)
        if file_intel is not None and not isinstance(file_intel, FileIntel):
            file_intel = None
        system, label = select_write_file_ae_system_instructions()
        return BundleAIContext(
            ae_system_instructions=system,
            ae_external_context=render_file_external_context(file_intel),
            ae_prompt_label=label,
        )

    @staticmethod
    def _path_matches(target: str, patterns: list[str]) -> bool:
        target = normalize_virtual_path(target)
        for pattern in patterns:
            norm_pattern = normalize_virtual_path(pattern) if "*" not in pattern else pattern
            if target.rstrip("/") == norm_pattern.rstrip("/"):
                return True
            if norm_pattern.endswith("/") and target.startswith(norm_pattern):
                return True
            if fnmatch.fnmatch(target, pattern):
                return True
            if fnmatch.fnmatch(target.rstrip("/"), pattern):
                return True
            if pattern.endswith("/*") and target.rstrip("/") == pattern[:-2]:
                return True
        return False
