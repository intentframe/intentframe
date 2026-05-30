"""Public sandbox execution plan model for executor packs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .templates import SandboxTemplate


@dataclass(frozen=True)
class ExecutionPlan:
    """Everything a sandbox engine needs to build an enforcement profile."""

    template: SandboxTemplate
    allowed_read_paths: tuple[str, ...]
    allowed_write_paths: tuple[str, ...]
    deny_write_paths: tuple[str, ...]
    deny_access_paths: tuple[str, ...]
    working_directory: str | None = None
    executor_venv_path: str | None = None
    sandbox_escalate: Literal["none", "sudo"] = "none"
