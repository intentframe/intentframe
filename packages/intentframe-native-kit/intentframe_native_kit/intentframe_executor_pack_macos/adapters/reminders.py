"""
Reminders adapter -- delegates to the native platform server (macos-appkit-server).

The Swift server owns the TCC grant and talks to EventKit directly.
This adapter is a thin RPC client over Unix domain socket.

Actions: CREATE_REMINDER, LIST_REMINDERS, COMPLETE_REMINDER,
         UPDATE_REMINDER, DELETE_REMINDER, LIST_REMINDER_LISTS

Required: macos-appkit-server must be running.
"""

from __future__ import annotations

import logging

from intentframe_native_kit.action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult
from ._platform_client import (
    platform_execute,
    platform_rollback,
)

logger = logging.getLogger(__name__)


def _to_result(resp: dict) -> ExecutionResult:
    return ExecutionResult(
        success=resp.get("success", False),
        data=resp.get("data"),
        error=resp.get("error"),
        rollback_available=resp.get("rollback_available", False),
        rollback_id=resp.get("rollback_id"),
    )


class RemindersAdapter(CapabilityAdapter):
    """macOS Reminders adapter — RPC client to the native platform server."""

    def __init__(self, **_kwargs) -> None:
        from ..permissions import check_adapter_permission
        check_adapter_permission("reminders")

    def supported_actions(self) -> list[str]:
        return [
            ActionType.CREATE_REMINDER.value,
            ActionType.LIST_REMINDERS.value,
            ActionType.LIST_REMINDER_LISTS.value,
            ActionType.COMPLETE_REMINDER.value,
            ActionType.UPDATE_REMINDER.value,
            ActionType.DELETE_REMINDER.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="reminders",
            name="Reminders Adapter",
            description="macOS Reminders via native platform server: create, list, complete, update, delete",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        resp = await platform_execute("reminders", action, params)
        return _to_result(resp)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        resp = await platform_rollback("reminders", rollback_id)
        return _to_result(resp)
