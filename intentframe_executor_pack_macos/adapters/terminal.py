"""
Terminal adapter -- shell command execution via asyncio.subprocess.

Provides controlled shell command execution with timeout, output
capture, and working directory support. Commands run as the executor
process user with a cleaned environment (no inherited secrets).

Defense in depth:
    The user's blocked_patterns (in TerminalConstraints) are enforced
    by the Guardian's TerminalChecker BEFORE the command reaches this
    adapter. command_shield.quick_check() is the non-negotiable last
    resort — it catches catastrophic operations even if the policy
    layer is misconfigured, missing, or bypassed.

Actions: RUN_COMMAND
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from action_registry import ActionType
from command_shield.env import clean_env
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)

MAX_OUTPUT_SIZE = 1024 * 1024  # 1 MB
DEFAULT_COMMAND_TIMEOUT = 30.0


class TerminalAdapter(CapabilityAdapter):
    """Shell command execution adapter."""

    def __init__(
        self,
        sandbox_engine=None,
        sandbox_planner=None,
        sandbox_config=None,
        pack_options: dict[str, dict[str, Any]] | None = None,
        **_kwargs,
    ) -> None:
        from intentframe_executor_pack_macos.sandbox import MacOSSandboxEngine
        from intentframe_executor_pack_macos.sandbox.config import SandboxConfig
        from intentframe_executor_pack_macos.sandbox.planner import SandboxPlanner
        from intentframe_executor_pack_macos.sandbox.venv import resolve_executor_venv_path

        raw_config = sandbox_config
        if raw_config is None and pack_options is not None:
            raw_config = pack_options.get("sandbox")

        if isinstance(raw_config, SandboxConfig):
            self._sandbox_config = raw_config
        elif raw_config is None:
            self._sandbox_config = SandboxConfig()
        else:
            self._sandbox_config = SandboxConfig.model_validate(raw_config)

        self._sandbox_engine = sandbox_engine
        self._sandbox_planner = sandbox_planner
        if self._sandbox_config.enabled:
            self._sandbox_engine = self._sandbox_engine or MacOSSandboxEngine()
            if self._sandbox_engine.available():
                self._sandbox_planner = self._sandbox_planner or SandboxPlanner(self._sandbox_config)
                if (
                    self._sandbox_config.executor_venv_required
                    and self._sandbox_planner.executor_venv_path is None
                ):
                    resolved = resolve_executor_venv_path(self._sandbox_config)
                    raise RuntimeError(
                        "Executor venv is required but not usable. "
                        "Expected a Python venv with bin/python3 at: "
                        f"{resolved or '<unresolved>'}. "
                        "Run `bash intentframe_setup.sh` to provision it, or "
                        "set `pack_options.sandbox.executor_venv_required: false` "
                        "to allow fallback to system python3."
                    )
            else:
                logger.warning(
                    "Sandbox enabled but engine unavailable on this platform -- "
                    "RUN_COMMAND will be rejected at request time"
                )

    def supported_actions(self) -> list[str]:
        return [ActionType.RUN_COMMAND.value]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="terminal",
            name="Terminal Adapter",
            description="Execute shell commands with output capture",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        if action != "RUN_COMMAND":
            return ExecutionResult(success=False, error=f"Unknown action: {action}")

        command = params.get("command", "")
        if not command:
            return ExecutionResult(success=False, error="No command provided")

        from intentframe_native_bundles.executor.floors import check_terminal_execute

        report = check_terminal_execute(command)
        if report.is_catastrophic:
            matched = report.signals[0].signal_id if report.signals else "unknown"
            logger.warning("Blocked catastrophic command: pattern=%r command=%s", matched, command[:120])
            return ExecutionResult(
                success=False,
                error=f"Command blocked — matched catastrophic pattern: {matched}",
            )

        working_dir = params.get("working_directory")
        if working_dir is None and self._sandbox_config and self._sandbox_config.enabled:
            working_dir = os.path.expanduser(self._sandbox_config.working_directory)
        timeout = params.get("timeout", DEFAULT_COMMAND_TIMEOUT)

        # ── Sandbox wrapping ──────────────────────────────────────────────
        sandboxed = None
        if self._sandbox_config and self._sandbox_config.enabled:
            if not self._sandbox_engine or not self._sandbox_planner:
                return ExecutionResult(
                    success=False,
                    error="Sandbox enabled but engine unavailable on this platform -- RUN_COMMAND blocked",
                )

            plan = self._sandbox_planner.plan(working_directory=working_dir)
            sandboxed = self._sandbox_engine.wrap(command, plan)
            logger.debug(
                "Sandbox: template=%s command=%s",
                plan.template.value, command[:120],
            )

        try:
            if sandboxed is not None:
                run_env = clean_env()
                run_env.update(sandboxed.env_overrides)
                process = await asyncio.create_subprocess_exec(
                    *sandboxed.argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    env=run_env,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    env=clean_env(),
                )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            stdout_str = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_SIZE]
            stderr_str = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_SIZE]

            return ExecutionResult(
                success=process.returncode == 0,
                data={
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "return_code": process.returncode,
                    "command": command,
                },
                error=stderr_str if process.returncode != 0 else None,
            )

        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error=f"Command timed out after {timeout}s: {command[:100]}",
            )

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            error="Shell command execution is irreversible",
        )
