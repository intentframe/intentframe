"""Host files action bundle — real-path file family."""

from __future__ import annotations

import fnmatch

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame
from resource_registry.floor import canonicalize_real_path

from intentframe_native_bundles.shared.files.ai_context import (
    render_file_external_context,
    select_write_file_ae_system_instructions,
)
from intentframe_native_bundles.shared.files.evidence import FileIntel
from intentframe_native_bundles.shared.files.evidence_keys import FILE_INTEL_KEY
from intentframe_native_bundles.shared.files.pre_pipeline import run_files_pre_pipeline
from intentframe_native_bundles.actions.host_files.constraints import HostFileConstraints
from intentframe_native_bundles.actions.host_files.deterministic import (
    HOST_FILE_ACTIONS,
    decide_host_file_floor,
)
from intentframe_native_bundles.actions.host_files.onboarding_guardrails import (
    host_files_onboarding_guardrails,
)
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleAIContext,
    BundleContext,
    BundlePhaseOutcome,
)


class HostFilesActionBundle(ActionBundle):
    bundle_id = "host_files"
    action_ids = HOST_FILE_ACTIONS
    passive_read_action_ids = frozenset({
        ActionType.READ_HOST_FILE.value,
        ActionType.LIST_HOST_DIRECTORY.value,
    })

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        if intent.action.value == ActionType.WRITE_HOST_FILE.value:
            ctx.evidence[FILE_INTEL_KEY] = run_files_pre_pipeline(intent, verbose=verbose)
        return BundlePhaseOutcome.continue_(ctx)

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            HostFileConstraints.model_validate(action_permission.constraints)

    async def enforce_constraints(
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
        constraints = HostFileConstraints.model_validate(action_permission.constraints)
        if not self._path_matches(intent.target, constraints.allowed_host_paths):
            return BundlePhaseOutcome.block(
                ctx,
                reason=(
                    f"Constraint violation: Host path '{intent.target}' "
                    "not in allowed host paths"
                ),
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    async def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = HostFileConstraints.model_validate(action_permission.constraints)
        return f"Allowed host paths: {', '.join(constraints.allowed_host_paths)}"

    def onboarding_guardrails(self) -> str:
        return host_files_onboarding_guardrails()

    async def structural_gates(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        outcome = decide_host_file_floor(intent, ctx)
        if outcome is None:
            return BundlePhaseOutcome.continue_(ctx)
        return outcome

    async def build_ai_context(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        del action_permission
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

    @staticmethod
    def _path_matches(target: str, patterns: list[str]) -> bool:
        canonical_target = canonicalize_real_path(target)
        for pattern in patterns:
            canonical_pattern = (
                canonicalize_real_path(pattern) if "*" not in pattern else pattern
            )
            if canonical_target.rstrip("/") == canonical_pattern.rstrip("/"):
                return True
            expanded_pattern = (
                canonicalize_real_path(pattern.split("*", 1)[0]) + "*"
                if "*" in pattern and pattern.startswith("~")
                else pattern
            )
            if fnmatch.fnmatch(canonical_target, expanded_pattern):
                return True
            if fnmatch.fnmatch(canonical_target.rstrip("/"), expanded_pattern):
                return True
            if pattern.endswith("/*") and canonical_target.rstrip("/") == (
                canonicalize_real_path(pattern[:-2])
            ):
                return True
        return False
