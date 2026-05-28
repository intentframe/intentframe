"""
Calendar adapter -- delegates to the native platform server (macos-appkit-server).

The Swift server owns the TCC grant and talks to EventKit directly.
This adapter is a thin RPC client: it serializes the request, sends it
over the Unix domain socket, and translates the response back to an
ExecutionResult.

Actions: CREATE_EVENT, LIST_EVENTS, DELETE_EVENT, UPDATE_EVENT, SEARCH_EVENTS, LIST_CALENDARS

Required: macos-appkit-server must be running.
"""

from __future__ import annotations

import logging

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult
from executor.platforms.macos.adapters._platform_client import (
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


class CalendarAdapter(CapabilityAdapter):
    """macOS Calendar adapter — RPC client to the native platform server."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            ActionType.CREATE_EVENT.value,
            ActionType.LIST_EVENTS.value,
            ActionType.LIST_CALENDARS.value,
            ActionType.UPDATE_EVENT.value,
            ActionType.DELETE_EVENT.value,
            ActionType.SEARCH_EVENTS.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="calendar",
            name="Calendar Adapter",
            description="macOS Calendar via native platform server: create, list, update, delete, search events",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        resp = await platform_execute("calendar", action, params)
        return _to_result(resp)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        resp = await platform_rollback("calendar", rollback_id)
        return _to_result(resp)
