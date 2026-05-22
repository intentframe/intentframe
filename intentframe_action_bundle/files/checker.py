"""Constraint checker for FILE category actions."""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_core.paths import normalize_virtual_path
from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker
from policy_registry.constraints.file import FileConstraints


class FileChecker(ConstraintChecker):
    """Path-based constraint enforcement for file operations."""

    @staticmethod
    def _path_matches(target: str, patterns: list[str]) -> bool:
        """Check if target matches any of the allowed path patterns.

        Normalizes the target so /home, /home/, ~/Documents all work.
        Also supports parent-match: /home/ is allowed if /home/* is a pattern,
        because listing a directory that contains allowed children is valid.
        """
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

    def check(
        self,
        intent: IntentFrame,
        constraints: FileConstraints,
        context: CheckContext | None = None,
    ) -> tuple[bool, str]:
        del context  # file checks are pure path/target today
        if not self._path_matches(intent.target, constraints.allowed_paths):
            return False, f"Path '{intent.target}' not in allowed paths"
        return True, ""

    def summarize(self, constraints: FileConstraints) -> str:
        return f"Allowed paths: {', '.join(constraints.allowed_paths)}"
