"""
Clipboard adapter -- macOS pasteboard access via subprocess (pbcopy/pbpaste).

Actions: GET_CLIPBOARD, SET_CLIPBOARD
"""

from __future__ import annotations

import asyncio
import subprocess

from intentframe_native_kit.action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult


class ClipboardAdapter(CapabilityAdapter):
    """macOS clipboard adapter using pbcopy/pbpaste."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            ActionType.GET_CLIPBOARD.value,
            ActionType.SET_CLIPBOARD.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="clipboard",
            name="Clipboard Adapter",
            description="macOS clipboard: get and set pasteboard content",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        if action == "GET_CLIPBOARD":
            return self._get_clipboard()
        if action == "SET_CLIPBOARD":
            return self._set_clipboard(params)
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    @staticmethod
    def _get_clipboard() -> ExecutionResult:
        try:
            result = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=5
            )
            content = result.stdout
            return ExecutionResult(
                success=True,
                data={"content": content, "length": len(content)},
            )
        except Exception as exc:
            return ExecutionResult(success=False, error=f"Failed to read clipboard: {exc}")

    @staticmethod
    def _set_clipboard(params: dict) -> ExecutionResult:
        content = params.get("content", "")

        try:
            subprocess.run(
                ["pbcopy"], input=content, text=True, timeout=5, check=True
            )
            return ExecutionResult(
                success=True,
                data={"length": len(content), "set": True},
                rollback_available=True,
                rollback_id="clipboard_set",
            )
        except Exception as exc:
            return ExecutionResult(success=False, error=f"Failed to set clipboard: {exc}")

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Clipboard rollback not implemented")
