"""
Messages adapter -- delegates to the native platform server (macos-appkit-server).

The Swift server sends messages via osascript subprocess (non-blocking) and
hides Messages.app only if it wasn't already running. SQLite reads for
READ_MESSAGES are handled natively without AppleScript.

Actions: SEND_MESSAGE, READ_MESSAGES

Required: macos-appkit-server must be running.
"""

from __future__ import annotations

import logging

from intentframe_native_kit.action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult
from ._platform_client import platform_execute

logger = logging.getLogger(__name__)


def _to_result(resp: dict) -> ExecutionResult:
    return ExecutionResult(
        success=resp.get("success", False),
        data=resp.get("data"),
        error=resp.get("error"),
    )


class MessagesAdapter(CapabilityAdapter):
    """macOS Messages adapter — RPC client to the native platform server."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [ActionType.SEND_MESSAGE.value, ActionType.READ_MESSAGES.value]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="messages",
            name="Messages Adapter",
            description="macOS Messages via native platform server: send and read messages",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        if action not in self.supported_actions():
            return ExecutionResult(success=False, error=f"Unknown action: {action}")
        resp = await platform_execute("messages", action, params)
        return _to_result(resp)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Message send is irreversible")
