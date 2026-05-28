"""
Notes adapter -- delegates to the native platform server (macos-appkit-server).

The Swift server uses NSAppleScript (in-process) for writes to prevent Notes.app
from stealing focus, and SQLite for reads. This adapter is a thin RPC client.

Actions: CREATE_NOTE, LIST_NOTES, READ_NOTE, DELETE_NOTE

Required: macos-appkit-server must be running.
"""

from __future__ import annotations

import logging

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult
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


class NotesAdapter(CapabilityAdapter):
    """macOS Notes adapter — RPC client to the native platform server."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            ActionType.CREATE_NOTE.value,
            ActionType.LIST_NOTES.value,
            ActionType.READ_NOTE.value,
            ActionType.DELETE_NOTE.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="notes",
            name="Notes Adapter",
            description="macOS Notes via native platform server: create, list, read, delete",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        resp = await platform_execute("notes", action, params)
        return _to_result(resp)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        resp = await platform_rollback("notes", rollback_id)
        return _to_result(resp)
