"""Constraint checker for HOST_FILE category actions.

Mirrors :class:`intentframe_components.guardian.checkers.file.FileChecker`
but operates on real host filesystem paths rather than virtual paths.
The single operational difference is path canonicalization: this checker
calls :func:`resource_registry.floor.canonicalize_real_path` (``~``
expansion + symlink resolution) where ``FileChecker`` calls
``normalize_virtual_path``.  The two vocabularies must not be mixed —
see the docstring on :class:`policy_registry.constraints.host_file.HostFileConstraints`.
"""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker
from policy_registry.constraints.host_file import HostFileConstraints
from resource_registry.floor import canonicalize_real_path


class HostFileChecker(ConstraintChecker):
    """Real-path constraint enforcement for HOST_FILE operations."""

    @staticmethod
    def _path_matches(target: str, patterns: list[str]) -> bool:
        """Check if *target* matches any of the allowed real-path patterns.

        Both *target* and *patterns* are canonicalized (``~`` expansion +
        symlink resolution) before matching so agent-supplied ``~/...``
        paths compare against user-supplied ``~/...`` patterns
        consistently.

        Only two pattern shapes are supported — trailing-slash
        directory shorthand is rejected at policy load time by
        :class:`HostFileConstraints` and therefore never reaches this
        matcher:

          - **exact path** (no ``*``): ``~/Documents/note.txt``.  The
            canonicalized target must equal the canonicalized pattern
            (modulo trailing slash, which ``Path.resolve`` strips
            anyway).
          - **subtree glob** (contains ``*``): ``~/Documents/*``.  The
            raw pattern is passed through :func:`fnmatch.fnmatch`
            against the canonicalized target.  A ``~``-prefixed glob
            is first ``~``-expanded so ``~/Documents/*`` can match
            ``/Users/me/Documents/foo.txt``.

        Deliberately **not** implemented: trailing-slash prefix match
        (``pattern.endswith("/")``).  That branch is dead on real
        paths because :func:`canonicalize_real_path` strips the
        separator; rather than resurrect it via a parallel non-
        canonical code path (and the allowlist-widening risk that
        carries), :class:`HostFileConstraints` rejects the syntax
        outright.
        """
        canonical_target = canonicalize_real_path(target)
        for pattern in patterns:
            canonical_pattern = (
                canonicalize_real_path(pattern) if "*" not in pattern else pattern
            )
            if canonical_target.rstrip("/") == canonical_pattern.rstrip("/"):
                return True
            # fnmatch is applied against the canonicalized target.
            # For ``~``-prefixed globs we first expand the pre-``*``
            # stem so ``~/Documents/*`` compares against the
            # canonicalized target (``/Users/me/Documents/foo.txt``)
            # consistently across platforms.
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

    def check(
        self,
        intent: IntentFrame,
        constraints: HostFileConstraints,
        context: CheckContext | None = None,
    ) -> tuple[bool, str]:
        del context  # host-file checks are pure path/target today
        if not self._path_matches(intent.target, constraints.allowed_host_paths):
            return False, f"Host path '{intent.target}' not in allowed host paths"
        return True, ""

    def summarize(self, constraints: HostFileConstraints) -> str:
        return f"Allowed host paths: {', '.join(constraints.allowed_host_paths)}"
