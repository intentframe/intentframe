"""Deletion domain module — deterministic structural enforcement."""

from __future__ import annotations

import fnmatch

from action_registry.types import DomainType
from intentframe_core.types import IntentFrame
from policy_registry.domains.base import DomainConstraints
from policy_registry.domains.deletion import DeletionConstraints
from intentframe_components.guardian.domains.base import DomainModule


class DeletionModule(DomainModule):
    """Structural enforcer for the deletion domain.

    Checks that can BLOCK (deterministic, before AI):
    - target not in allowed_paths
    - block_irreversible and data.irreversible is True
    - require_confirmation (not yet implemented — needs session history)

    What this module CANNOT catch (AI handles after module passes):
    - Deleting the right file for the wrong reason (scope/context)
    - Files with hidden dependencies
    - Socially engineered deletion prompts
    """

    @property
    def domain(self) -> DomainType:
        return DomainType.DELETION

    def check(
        self,
        intent: IntentFrame,
        constraints: DomainConstraints,
    ) -> tuple[bool, str]:
        if not isinstance(constraints, DeletionConstraints):
            return True, ""

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
