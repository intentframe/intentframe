"""Deletion domain bundle — structural enforcement for destructive intents."""

from __future__ import annotations

import fnmatch
from typing import Any

from intentframe_core.types import IntentFrame
from intentframe_bundle_sdk.domain import DomainBundle
from intentframe_bundle_sdk.types import BundleContext
from policy_registry.domains.deletion import DeletionConstraints
from policy_registry.domains.base import DomainConstraints


class DeletionDomainBundle(DomainBundle):
    domain_id = "deletion"

    def validate_constraints(self, constraints: dict[str, Any]) -> None:
        DeletionConstraints.model_validate(constraints)

    def check_domain(
        self,
        intent: IntentFrame,
        constraints: Any | None,
        ctx: BundleContext,
    ) -> tuple[bool, str]:
        del ctx
        if constraints is None:
            return True, ""
        if isinstance(constraints, DomainConstraints) and not isinstance(
            constraints, DeletionConstraints
        ):
            return True, ""
        if not isinstance(constraints, DeletionConstraints):
            constraints = DeletionConstraints.model_validate(constraints)

        data = intent.data or {}

        if constraints.allowed_paths is not None:
            target = data.get("target_path", intent.target)
            if not self._path_matches(target, constraints.allowed_paths):
                return False, (
                    f"Path '{target}' not in allowed deletion paths"
                )

        if constraints.block_irreversible:
            irreversible = data.get("irreversible", True)
            if irreversible:
                return False, "Irreversible deletions are blocked by domain policy"

        return True, ""

    def summarize_constraints(self, constraints: Any) -> str:
        if not isinstance(constraints, DeletionConstraints):
            constraints = DeletionConstraints.model_validate(constraints)
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
