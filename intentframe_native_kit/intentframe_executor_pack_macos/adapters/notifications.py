"""
Notifications adapter -- delegates to the native platform server (macos-appkit-server).

The Swift server uses UNUserNotificationCenter so notifications appear with the
IntentFrame app icon and name instead of "Script Editor".

Actions: SHOW_NOTIFICATION

Required: macos-appkit-server must be running.
"""

from __future__ import annotations

import logging

from intentframe_native_kit.action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult
from ._platform_client import platform_execute

logger = logging.getLogger(__name__)


class NotificationsAdapter(CapabilityAdapter):
    """macOS notification center adapter — RPC client to the native platform server."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [ActionType.SHOW_NOTIFICATION.value]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="notifications",
            name="Notifications Adapter",
            description="macOS notification center via native platform server (branded notifications)",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        if action != "SHOW_NOTIFICATION":
            return ExecutionResult(success=False, error=f"Unknown action: {action}")
        resp = await platform_execute("notifications", action, params)
        return ExecutionResult(
            success=resp.get("success", False),
            data=resp.get("data"),
            error=resp.get("error"),
        )

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Notifications are irreversible")
