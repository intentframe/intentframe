"""
Shared HTTP-over-UDS client for the native platform server (macos-appkit-server).

All TCC-gated adapters (calendar, reminders, contacts) delegate to the Swift
server through this thin client. The server listens on a Unix domain socket.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET = Path.home() / ".intentframe" / "run" / "platform.sock"
_TIMEOUT = 30.0

_SERVER_DOWN_MSG = "This capability is temporarily unavailable."

_SERVER_DOWN_LOG = (
    "Platform server (macos-appkit-server) is not reachable at %s. "
    "Start it before using native platform features "
    "(calendar, reminders, contacts, notes, notifications, user dialogs, system control)."
)


def _socket_path() -> str:
    return os.environ.get("PLATFORM_SOCKET", str(_DEFAULT_SOCKET))


def _make_async_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=_socket_path())
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://platform-server",
        timeout=_TIMEOUT,
    )


class PlatformServerUnavailable(Exception):
    """Raised when the platform server cannot be reached."""

    def __init__(self) -> None:
        super().__init__(_SERVER_DOWN_MSG)


def _raise_unavailable() -> None:
    """Log full diagnostics for developers, raise a clean exception for the agent."""
    logger.error(_SERVER_DOWN_LOG, _socket_path())
    raise PlatformServerUnavailable()


async def platform_execute(adapter: str, action: str, params: dict) -> dict:
    """Send an execute request to the platform server and return the response dict."""
    try:
        async with _make_async_client() as client:
            resp = await client.post(
                "/execute",
                json={"adapter": adapter, "action": action, "params": params},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        _raise_unavailable()


async def platform_rollback(adapter: str, rollback_id: str) -> dict:
    """Send a rollback request to the platform server and return the response dict."""
    try:
        async with _make_async_client() as client:
            resp = await client.post(
                "/rollback",
                json={"adapter": adapter, "rollback_id": rollback_id},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        _raise_unavailable()


async def platform_health() -> dict:
    """Check platform server health."""
    try:
        async with _make_async_client() as client:
            resp = await client.get("/health")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        _raise_unavailable()


async def platform_permissions() -> dict:
    """Get current TCC permission status."""
    try:
        async with _make_async_client() as client:
            resp = await client.get("/permissions")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        _raise_unavailable()
