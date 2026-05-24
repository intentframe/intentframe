"""Deletion domain bundle."""

from __future__ import annotations

import fnmatch

from action_registry.types import DomainType
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.domains.deletion.constraints import DeletionConstraints
from intentframe_bundle_sdk.domain import DomainBundle
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome


class DeletionDomainBundle(DomainBundle):
    bundle_id = "deletion"
    domain_type = DomainType.DELETION

    def validate(self, domain_constraints: dict | None) -> None:
        if domain_constraints is not None:
            DeletionConstraints.model_validate(domain_constraints)

    def enforce(
        self,
        intent: IntentFrame,
        domain_constraints: dict | None,
    ) -> BundlePhaseOutcome:
        ctx = BundleContext(intent=intent.model_copy(deep=True))
        if domain_constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = DeletionConstraints.model_validate(domain_constraints)
        data = intent.data or {}

        if constraints.allowed_paths is not None:
            target = data.get("target_path", intent.target)
            if not self._path_matches(target, constraints.allowed_paths):
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        f"Domain violation (deletion): Path '{target}' "
                        "not in allowed deletion paths"
                    ),
                    matched_gate="domain",
                )

        if constraints.block_irreversible:
            irreversible = data.get("irreversible", True)
            if irreversible:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        "Domain violation (deletion): Irreversible deletions "
                        "are blocked by domain policy"
                    ),
                    matched_gate="domain",
                )

        return BundlePhaseOutcome.continue_(ctx)

    def describe(self, domain_constraints: dict | None) -> str | None:
        if domain_constraints is None:
            return None
        constraints = DeletionConstraints.model_validate(domain_constraints)
        parts: list[str] = []
        if constraints.allowed_paths is not None:
            parts.append(f"allowed_paths={constraints.allowed_paths}")
        if constraints.block_irreversible:
            parts.append("block_irreversible=true")
        if constraints.require_confirmation:
            parts.append("require_confirmation=true")
        return "; ".join(parts) if parts else "deletion domain constraints configured"

    @staticmethod
    def _path_matches(target: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            if target == pattern:
                return True
            if pattern.endswith("/") and target.startswith(pattern):
                return True
            if fnmatch.fnmatch(target, pattern):
                return True
        return False
