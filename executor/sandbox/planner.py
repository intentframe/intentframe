"""Sandbox planner -- computes template and filesystem scope.

Every command gets the same sandbox template: ``max(allowed_templates)``
from config.  The admin decides the privilege ceiling once; the planner
applies it uniformly.  No per-command classification.

All paths in the ``ExecutionPlan`` are **canonical** (symlinks resolved
via ``os.path.realpath``).  Critical on macOS where ``/var`` →
``/private/var`` and ``/tmp`` → ``/private/tmp``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from executor.config.schema import SandboxConfig
from executor.sandbox.pathing import canonical_sandbox_path
from executor.sandbox.templates import (
    NON_NEGOTIABLE_DENY_ACCESS,
    NON_NEGOTIABLE_DENY_WRITE,
    SandboxTemplate,
    TEMPLATE_ORDER,
)

_TEMPLATE_RANK = {t: i for i, t in enumerate(TEMPLATE_ORDER)}


@dataclass(frozen=True)
class ExecutionPlan:
    """Everything the engine needs to build a sandbox profile.

    All paths are canonical (realpath-resolved).
    """

    template: SandboxTemplate
    allowed_read_paths: tuple[str, ...]
    allowed_write_paths: tuple[str, ...]
    deny_write_paths: tuple[str, ...]
    deny_access_paths: tuple[str, ...]
    working_directory: str | None = None


class SandboxPlanner:
    """Stateless planner -- one instance per executor lifetime."""

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config

        allowed_set: set[SandboxTemplate] = set()
        for name in config.allowed_templates:
            try:
                allowed_set.add(SandboxTemplate(name))
            except ValueError:
                pass
        self._allowed_templates = allowed_set

        self._template = self._resolve_template(allowed_set)

        self._write_paths = self._resolve_write_paths(config)

        self._deny_write = tuple(
            canonical_sandbox_path(p) for p in NON_NEGOTIABLE_DENY_WRITE
        )
        self._deny_access = tuple(
            canonical_sandbox_path(p) for p in NON_NEGOTIABLE_DENY_ACCESS
        )

    @property
    def template(self) -> SandboxTemplate:
        """The single template applied to all commands."""
        return self._template

    def plan(self, working_directory: str | None = None) -> ExecutionPlan:
        """Produce an ``ExecutionPlan`` using the config-driven template."""
        write_paths = list(self._write_paths)
        if working_directory:
            canon_wd = canonical_sandbox_path(working_directory)
            if canon_wd not in write_paths:
                write_paths.append(canon_wd)

        return ExecutionPlan(
            template=self._template,
            allowed_read_paths=(),
            allowed_write_paths=tuple(write_paths),
            deny_write_paths=self._deny_write,
            deny_access_paths=self._deny_access,
            working_directory=working_directory,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_template(
        allowed: set[SandboxTemplate],
    ) -> SandboxTemplate:
        if not allowed:
            return SandboxTemplate.FILE_READ_ONLY
        return max(allowed, key=lambda t: _TEMPLATE_RANK.get(t, 0))

    @staticmethod
    def _resolve_write_paths(config: SandboxConfig) -> list[str]:
        """Canonicalize write paths from sandbox config."""
        paths: list[str] = []
        for p in config.allowed_write_paths:
            canon = canonical_sandbox_path(os.path.expanduser(p))
            if canon not in paths:
                paths.append(canon)
        return paths
