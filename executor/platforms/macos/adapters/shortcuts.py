"""
Shortcuts adapter -- macOS Shortcuts.app via CLI.

Actions: RUN_SHORTCUT, LIST_SHORTCUTS
"""

from __future__ import annotations

import asyncio
import subprocess

from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult


class ShortcutsAdapter(CapabilityAdapter):
    """macOS Shortcuts.app adapter via shortcuts CLI."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return ["RUN_SHORTCUT", "LIST_SHORTCUTS"]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="shortcuts",
            name="Shortcuts Adapter",
            description="macOS Shortcuts.app: run and list shortcuts",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        if action == "RUN_SHORTCUT":
            return self._run_shortcut(params)
        if action == "LIST_SHORTCUTS":
            return self._list_shortcuts()
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    @staticmethod
    def _run_shortcut(params: dict) -> ExecutionResult:
        name = params.get("name", "")
        input_text = params.get("input", "")

        if not name:
            return ExecutionResult(success=False, error="Shortcut name required")

        cmd = ["shortcuts", "run", name]
        try:
            result = subprocess.run(
                cmd,
                input=input_text if input_text else None,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return ExecutionResult(
                success=result.returncode == 0,
                data={
                    "name": name,
                    "output": result.stdout,
                    "return_code": result.returncode,
                },
                error=result.stderr if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(success=False, error=f"Shortcut timed out: {name}")
        except FileNotFoundError:
            return ExecutionResult(success=False, error="shortcuts CLI not found")

    @staticmethod
    def _list_shortcuts() -> ExecutionResult:
        try:
            result = subprocess.run(
                ["shortcuts", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            shortcuts = [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
            return ExecutionResult(
                success=True,
                data={"shortcuts": shortcuts, "count": len(shortcuts)},
            )
        except FileNotFoundError:
            return ExecutionResult(success=False, error="shortcuts CLI not found")

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Shortcut execution is irreversible")
