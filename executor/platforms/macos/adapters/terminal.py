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

from action_registry import ActionType
from command_shield import quick_check
from command_shield.env import clean_env
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)

MAX_OUTPUT_SIZE = 1024 * 1024  # 1 MB
DEFAULT_COMMAND_TIMEOUT = 30.0


class TerminalAdapter(CapabilityAdapter):
    """Shell command execution adapter."""

    def __init__(self, **_kwargs) -> None:
        pass

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

        report = quick_check(command)
        if report.is_catastrophic:
            matched = report.signals[0].signal_id if report.signals else "unknown"
            logger.warning("Blocked catastrophic command: pattern=%r command=%s", matched, command[:120])
            return ExecutionResult(
                success=False,
                error=f"Command blocked — matched catastrophic pattern: {matched}",
            )

        working_dir = params.get("working_directory")
        timeout = params.get("timeout", DEFAULT_COMMAND_TIMEOUT)

        try:
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
