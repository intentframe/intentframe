"""Sandbox planner -- selects template and computes filesystem scope.

Given a ``CapabilityReport`` from the classifier, the planner:

1.  Picks the narrowest ``SandboxTemplate`` that covers all capabilities.
2.  Falls back to the opaque template if the report says ``opaque=True``.
3.  Rejects the command (returns ``None``) if the selected template is not
    in the executor's ``allowed_templates`` ceiling.
4.  Derives allowed/denied paths from the ``MountPointResolver``.

All paths stored in the ``ExecutionPlan`` are **canonical** (symlinks
resolved via ``os.path.realpath``).  This is critical on macOS where
``/var`` → ``/private/var`` and ``/tmp`` → ``/private/tmp``.
"""

from __future__ import annotations

from dataclasses import dataclass

from executor.config.schema import SandboxConfig
from executor.sandbox.capabilities import CapabilityReport
from executor.sandbox.pathing import canonical_sandbox_path
from executor.sandbox.templates import (
    NON_NEGOTIABLE_DENY_ACCESS,
    NON_NEGOTIABLE_DENY_WRITE,
    SandboxTemplate,
    TEMPLATE_ORDER,
    minimum_template,
)
from executor.services.virtual_filesystem import MountPointResolver


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

    def __init__(
        self,
        config: SandboxConfig,
        mount_resolver: MountPointResolver,
    ) -> None:
        self._config = config

        allowed_set: set[SandboxTemplate] = set()
        for name in config.allowed_templates:
            try:
                allowed_set.add(SandboxTemplate(name))
            except ValueError:
                pass
        self._allowed_templates = allowed_set

        self._default_template = self._safe_template(config.default_template)
        self._opaque_fallback = self._safe_template(config.opaque_fallback)

        self._read_paths, self._write_paths = self._resolve_mount_paths(
            mount_resolver
        )

        self._deny_write = tuple(
            canonical_sandbox_path(p) for p in NON_NEGOTIABLE_DENY_WRITE
        )
        self._deny_access = tuple(
            canonical_sandbox_path(p) for p in NON_NEGOTIABLE_DENY_ACCESS
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        report: CapabilityReport,
        working_directory: str | None = None,
    ) -> ExecutionPlan | None:
        """Produce an ``ExecutionPlan`` or ``None`` (= reject command)."""
        if report.opaque:
            tmpl = self._opaque_fallback
        else:
            tmpl = minimum_template(report.capabilities)
            if tmpl is None:
                tmpl = self._opaque_fallback

        if tmpl not in self._allowed_templates:
            if report.opaque:
                return None
            tmpl = self._find_allowed_covering(report)
            if tmpl is None:
                return None

        read_paths = list(self._read_paths)
        write_paths = list(self._write_paths)
        if working_directory:
            canon_wd = canonical_sandbox_path(working_directory)
            if canon_wd not in read_paths:
                read_paths.append(canon_wd)
            if canon_wd not in write_paths:
                write_paths.append(canon_wd)

        return ExecutionPlan(
            template=tmpl,
            allowed_read_paths=tuple(read_paths),
            allowed_write_paths=tuple(write_paths),
            deny_write_paths=self._deny_write,
            deny_access_paths=self._deny_access,
            working_directory=working_directory,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_allowed_covering(
        self, report: CapabilityReport
    ) -> SandboxTemplate | None:
        """Walk the lattice upward for the narrowest *allowed* template."""
        from executor.sandbox.templates import TEMPLATE_CAPABILITIES

        for tmpl in TEMPLATE_ORDER:
            if tmpl not in self._allowed_templates:
                continue
            if report.capabilities <= TEMPLATE_CAPABILITIES[tmpl]:
                return tmpl
        return None

    @staticmethod
    def _resolve_mount_paths(
        resolver: MountPointResolver,
    ) -> tuple[list[str], list[str]]:
        """Extract canonical real paths from mount configs."""
        read_paths: list[str] = []
        write_paths: list[str] = []
        for mount in resolver.mounts:
            real = canonical_sandbox_path(mount.real_path)
            read_paths.append(real)
            if mount.writable:
                write_paths.append(real)
        return read_paths, write_paths

    @staticmethod
    def _safe_template(name: str) -> SandboxTemplate:
        try:
            return SandboxTemplate(name)
        except ValueError:
            return SandboxTemplate.FILE_READ_ONLY
