"""Sandbox planner -- computes template and filesystem scope.

Every command gets the same sandbox template: ``max(allowed_templates)``
from config.  The admin decides the privilege ceiling once; the planner
applies it uniformly.  No per-command classification.

All paths in the ``ExecutionPlan`` are **canonical** (symlinks resolved
via ``os.path.realpath``).  Critical on macOS where ``/var`` →
``/private/var`` and ``/tmp`` → ``/private/tmp``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from executor.config.schema import SandboxConfig

logger = logging.getLogger(__name__)
from executor.sandbox.pathing import canonical_sandbox_path
from executor.sandbox.templates import (
    NON_NEGOTIABLE_DENY_ACCESS,
    NON_NEGOTIABLE_DENY_WRITE,
    SandboxTemplate,
    TEMPLATE_ORDER,
)
from executor.sandbox.venv import resolve_executor_venv_path, validate_executor_venv

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
    executor_venv_path: str | None = None
    # Per-command privilege-escalation intent propagated from
    # ``SandboxConfig.escalate``.  The engine combines it with the
    # runtime ``INTENTFRAME_ESCALATION_ARMED`` env (machine capability)
    # to decide whether to prepend ``sudo -n`` to the argv.
    sandbox_escalate: Literal["none", "sudo"] = "none"


class SandboxPlanner:
    """Stateless planner -- one instance per executor lifetime."""

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config

        allowed_set: set[SandboxTemplate] = set()
        for name in config.allowed_templates:
            try:
                allowed_set.add(SandboxTemplate(name))
            except ValueError:
                logger.warning(
                    "Ignoring unrecognised sandbox template %r in allowed_templates "
                    "(valid: %s)",
                    name,
                    ", ".join(t.value for t in TEMPLATE_ORDER),
                )
        self._allowed_templates = allowed_set

        self._template = self._resolve_template(allowed_set)
        if not allowed_set:
            logger.error(
                "No valid templates in allowed_templates — falling back to %s. "
                "Check executor.yaml sandbox.allowed_templates.",
                self._template.value,
            )

        self._write_paths = self._resolve_write_paths(config)

        self._deny_write = tuple(
            canonical_sandbox_path(p) for p in NON_NEGOTIABLE_DENY_WRITE
        )
        self._deny_access = tuple(
            canonical_sandbox_path(p) for p in NON_NEGOTIABLE_DENY_ACCESS
        )

        self._executor_venv_path = self._resolve_executor_venv(
            config, self._deny_access
        )

    @property
    def template(self) -> SandboxTemplate:
        """The single template applied to all commands."""
        return self._template

    @property
    def executor_venv_path(self) -> str | None:
        """Resolved absolute path to the executor venv, or ``None``."""
        return self._executor_venv_path

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
            executor_venv_path=self._executor_venv_path,
            sandbox_escalate=self._config.escalate,
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

    @staticmethod
    def _resolve_executor_venv(
        config: SandboxConfig, deny_access: tuple[str, ...],
    ) -> str | None:
        """Resolve + validate the executor venv path (once, at startup).

        Returns ``None`` when:
          1. The path cannot be resolved (bare root + no SUDO_USER).
          2. The venv is missing / lacks ``bin/python3``.
          3. The resolved path sits under a non-negotiable deny-access
             subpath -- the sandbox would deny reads on the interpreter
             binary, making ``exec`` fail with "Operation not permitted"
             even under UNRESTRICTED. This is a config mistake (e.g.
             nesting the venv under ``~/.intentframe``) and we fail
             loud rather than ship a broken deployment.

        Cases (1) and (2) log an error when
        ``executor_venv_required=True``; case (3) always logs an
        error. The startup layer
        (``executor.main.build_gateway``) is responsible for turning
        ``None`` + ``executor_venv_required=True`` into a fail-closed
        ConfigurationError.
        """
        path = resolve_executor_venv_path(config)
        if path is None:
            if config.executor_venv_required:
                logger.error(
                    "Executor venv unresolved (no SUDO_USER, running as "
                    "root, and sandbox.executor_venv_path not set). "
                    "Sandboxed RUN_COMMAND will have no Python venv."
                )
            return None

        if not validate_executor_venv(path):
            if config.executor_venv_required:
                logger.error(
                    "Executor venv missing or unusable at %s -- expected "
                    "<venv>/bin/python3. Provision via intentframe_setup.sh.",
                    path,
                )
                return None
            logger.warning(
                "Executor venv not found at %s; sandboxed Python will fall "
                "back to system python3 (executor_venv_required=False).",
                path,
            )
            return None

        collision = _find_deny_collision(path, deny_access)
        if collision is not None:
            logger.error(
                "Executor venv %s is nested under deny-access path %s. "
                "The sandbox would deny reads on bin/python3, making exec "
                "fail. Move the venv outside that subpath (default: "
                "~/.intentframe-venvs/executor).",
                path, collision,
            )
            return None

        logger.info("Executor venv: %s", path)
        return path


def _find_deny_collision(
    venv_path: str, deny_access: tuple[str, ...],
) -> str | None:
    """Return the deny-access entry that contains *venv_path*, or ``None``.

    Uses prefix matching on canonical paths with an explicit separator
    to avoid ``/a/bad`` matching ``/a/b``. Both sides are already
    canonicalized (realpath-resolved) by the callers, so this is a
    pure string comparison.
    """
    venv = venv_path.rstrip(os.sep)
    for deny in deny_access:
        d = deny.rstrip(os.sep)
        if venv == d or venv.startswith(d + os.sep):
            return deny
    return None
