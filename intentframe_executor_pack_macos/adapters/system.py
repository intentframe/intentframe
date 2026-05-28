"""
System adapter -- macOS system settings.

GET_SYSTEM_INFO is handled directly (stdlib).
All other actions delegate to the native platform server
(macos-appkit-server) via HTTP-over-UDS.

Actions: GET_SYSTEM_INFO,
         SET_VOLUME, GET_VOLUME, TOGGLE_MUTE, GET_MUTE,
         SET_BRIGHTNESS, GET_BRIGHTNESS,
         TOGGLE_DARK_MODE, GET_DARK_MODE
"""

from __future__ import annotations

import asyncio
import platform

from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult
from ._platform_client import platform_execute

_PLATFORM_ACTIONS = {
    "SET_VOLUME", "GET_VOLUME", "TOGGLE_MUTE", "GET_MUTE",
    "SET_BRIGHTNESS", "GET_BRIGHTNESS",
    "TOGGLE_DARK_MODE", "GET_DARK_MODE",
}


class SystemAdapter(CapabilityAdapter):
    """macOS system settings adapter."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            "GET_SYSTEM_INFO",
            "SET_VOLUME", "GET_VOLUME", "TOGGLE_MUTE", "GET_MUTE",
            "SET_BRIGHTNESS", "GET_BRIGHTNESS",
            "TOGGLE_DARK_MODE", "GET_DARK_MODE",
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="system",
            name="System Adapter",
            description="macOS system: info, volume, mute, brightness, dark mode",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        if action == "GET_SYSTEM_INFO":
            return await asyncio.to_thread(self._get_system_info)
        if action in _PLATFORM_ACTIONS:
            resp = await platform_execute("system", action, params)
            return ExecutionResult(
                success=resp.get("success", False),
                data=resp.get("data"),
                error=resp.get("error"),
            )
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    @staticmethod
    def _get_system_info() -> ExecutionResult:
        info = {
            "os": platform.system(),
            "os_version": platform.mac_ver()[0],
            "architecture": platform.machine(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
        }
        return ExecutionResult(success=True, data=info)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="System changes rollback not yet implemented")
