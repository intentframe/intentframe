"""Async HTTP client for the Jarvis API server over UDS.

Mirrors the sync client in ``jarvis.server_cli`` but uses
``httpx.AsyncClient`` so it integrates with the Telegram bot's
event loop.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger


# ---------------------------------------------------------------------------
# Typed errors — handlers translate these into user-facing messages
# ---------------------------------------------------------------------------

class JarvisBusyError(Exception):
    """Jarvis is handling another client's request (HTTP 429)."""

    def __init__(self, current_client: str) -> None:
        self.current_client = current_client
        super().__init__(f"Jarvis is busy talking to {current_client}")


class JarvisTimeoutError(Exception):
    """The chat exceeded the server's gate timeout (HTTP 504)."""


class JarvisServerError(Exception):
    """Unexpected server-side failure (HTTP 5xx)."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_BASE_URL = "http://jarvis-local"
_CLIENT_ID = "telegram"


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    """Parse response JSON, returning empty dict on failure."""
    try:
        return resp.json()
    except Exception:
        return {}


class JarvisClient:
    """Async client that talks to the Jarvis FastAPI server over UDS."""

    def __init__(self, socket_path: str) -> None:
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url=_BASE_URL,
            timeout=httpx.Timeout(connect=5.0, read=660.0, write=10.0, pool=10.0),
        )

    # -- public API -----------------------------------------------------------

    async def chat(self, message: str) -> str:
        """Send a message to Jarvis and return the response text."""
        resp = await self._client.post(
            "/chat",
            json={"message": message, "client": _CLIENT_ID},
        )
        if resp.status_code == 429:
            detail = _safe_json(resp).get("detail", {})
            raise JarvisBusyError(detail.get("current_client", "unknown"))
        if resp.status_code == 504:
            raise JarvisTimeoutError("Chat timed out on the server")
        if resp.status_code >= 500:
            detail = _safe_json(resp).get("detail", {})
            raise JarvisServerError(detail.get("message", f"Server error {resp.status_code}"))
        resp.raise_for_status()
        return resp.json()["response"]

    async def status(self) -> dict[str, Any]:
        """Return the Jarvis server status dict."""
        resp = await self._client.get("/status")
        resp.raise_for_status()
        return resp.json()

    async def is_healthy(self) -> bool:
        """Check whether the Jarvis server is reachable and healthy."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.RemoteProtocolError, OSError) as exc:
            logger.debug(f"Health check failed: {exc}")
            return False

    async def close(self) -> None:
        await self._client.aclose()
