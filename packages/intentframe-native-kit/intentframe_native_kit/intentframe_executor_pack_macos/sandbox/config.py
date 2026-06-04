"""macOS RUN_COMMAND sandbox configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SandboxConfig(BaseModel):
    """Configuration for the macOS RUN_COMMAND sandbox."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Master switch for RUN_COMMAND sandboxing.",
    )
    allowed_templates: list[str] = Field(
        default_factory=lambda: ["pure_compute", "file_read_only", "file_read_write"],
        description=(
            "Sandbox template ceiling. All commands run under the "
            "highest-privilege template in this list."
        ),
    )
    working_directory: str = Field(
        default="~/",
        description="Default cwd for sandboxed shell commands. Expanded at runtime.",
    )
    allowed_write_paths: list[str] = Field(
        default_factory=lambda: ["~/"],
        description="Paths where sandboxed commands can write. Expanded at runtime.",
    )
    executor_venv_path: str | None = Field(
        default=None,
        description="Absolute path to the executor's dedicated Python venv.",
    )
    executor_venv_required: bool = Field(
        default=True,
        description="Fail loud when the sandbox executor venv is missing or unusable.",
    )
    escalate: Literal["none", "sudo"] = Field(
        default="none",
        description="Per-command privilege escalation for RUN_COMMAND.",
    )
