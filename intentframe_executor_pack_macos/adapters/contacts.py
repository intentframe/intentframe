"""
Contacts adapter -- delegates to the native platform server (macos-appkit-server).

The Swift server owns the TCC grant and talks to the Contacts framework directly.
This adapter is a thin RPC client over Unix domain socket.

Actions: SEARCH_CONTACTS, ADD_CONTACT, GET_CONTACT,
         UPDATE_CONTACT, DELETE_CONTACT

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


class ContactsAdapter(CapabilityAdapter):
    """macOS Contacts adapter — RPC client to the native platform server."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            ActionType.SEARCH_CONTACTS.value,
            ActionType.GET_CONTACT.value,
            ActionType.ADD_CONTACT.value,
            ActionType.UPDATE_CONTACT.value,
            ActionType.DELETE_CONTACT.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="contacts",
            name="Contacts Adapter",
            description="macOS Contacts via native platform server: search, add, get, update, delete",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        resp = await platform_execute("contacts", action, params)
        return _to_result(resp)

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        resp = await platform_rollback("contacts", rollback_id)
        return _to_result(resp)
