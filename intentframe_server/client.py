"""
IntentFrame Client -- low-level HTTP transport to IntentFrame Core.

Used internally by the Actor SDK (intentframe_actor) to send
IntentFrames to the Runtime over UDS.

Two variants:
    IntentFrameClient      -- sync  (admin scripts, CLI tools, dashboard)
    AsyncIntentFrameClient -- async (used inside Actor SDK)

Not meant to be used directly by agent developers.  Agent developers
use the Actor SDK (``from intentframe_actor import Actor``).
"""

from __future__ import annotations

from typing import Any

import httpx

from intentframe_core.types import (
    AgentCapabilities,
    ExecutionResult,
    IntentFrame,
    RuntimeContext,
)

DEFAULT_SOCKET = "~/.intentframe/run/intentframe.sock"


# ── Sync Client ───────────────────────────────────────────────────────────────


class IntentFrameClient:
    """Sync HTTP client for the IntentFrame Core service.

    Provides the same interface as IntentFrameRuntime but over HTTP/UDS.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET,
        *,
        base_url: str | None = None,
    ) -> None:
        """Connect over a network URL (``base_url``) or a local UDS.

        ``base_url`` (or the ``INTENTFRAME_CORE_URL`` env var) makes the
        client talk to a remote runtime through the IntentFrame edge,
        e.g. ``https://intentframe.acme.com``.  When unset, the client
        falls back to the local UDS at ``socket_path``.
        """
        import os
        base_url = base_url or os.environ.get("INTENTFRAME_CORE_URL")
        if base_url:
            self._socket = None
            self._client = httpx.Client(
                base_url=base_url.rstrip("/"),
                timeout=120.0,
            )
        else:
            self._socket = os.path.expanduser(socket_path)
            self._transport = httpx.HTTPTransport(uds=self._socket)
            self._client = httpx.Client(
                transport=self._transport,
                base_url="http://intentframe",
                timeout=120.0,
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def handshake(
        self,
        capabilities: AgentCapabilities,
        user_id: str,
        agent_id: str,
    ) -> RuntimeContext:
        payload = {
            "capabilities": capabilities.model_dump(mode="json"),
            "user_context": {"user_id": user_id, "agent_id": agent_id},
        }
        resp = self._client.post("/handshake", json=payload)
        resp.raise_for_status()
        return RuntimeContext.model_validate(resp.json())

    def process_intent(
        self,
        intent: IntentFrame,
        user_id: str,
        agent_id: str,
    ) -> ExecutionResult:
        payload = {
            "intent": intent.model_dump(mode="json"),
            "user_context": {"user_id": user_id, "agent_id": agent_id},
        }
        resp = self._client.post("/process", json=payload)
        resp.raise_for_status()
        return ExecutionResult.model_validate(resp.json())

    def get_audit_log(self) -> list[dict[str, Any]]:
        resp = self._client.get("/audit")
        resp.raise_for_status()
        return resp.json()

    def clear_audit_log(self) -> None:
        resp = self._client.post("/audit/clear")
        resp.raise_for_status()


# ── Async Client ──────────────────────────────────────────────────────────────


class AsyncIntentFrameClient:
    """Async HTTP client for the IntentFrame Core service.

    Used internally by Actor SDK to send IntentFrames to the Runtime.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET,
        *,
        base_url: str | None = None,
    ) -> None:
        """Connect over a network URL (``base_url``) or a local UDS.

        ``base_url`` (or the ``INTENTFRAME_CORE_URL`` env var) makes the
        client talk to a remote runtime through the IntentFrame edge.
        When unset, it falls back to the local UDS at ``socket_path``.
        """
        import os
        base_url = base_url or os.environ.get("INTENTFRAME_CORE_URL")
        if base_url:
            self._socket = None
            self._client = httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                timeout=120.0,
            )
        else:
            self._socket = os.path.expanduser(socket_path)
            self._transport = httpx.AsyncHTTPTransport(uds=self._socket)
            self._client = httpx.AsyncClient(
                transport=self._transport,
                base_url="http://intentframe",
                timeout=120.0,
            )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def handshake(
        self,
        capabilities: AgentCapabilities,
        user_id: str,
        agent_id: str,
    ) -> RuntimeContext:
        payload = {
            "capabilities": capabilities.model_dump(mode="json"),
            "user_context": {"user_id": user_id, "agent_id": agent_id},
        }
        resp = await self._client.post("/handshake", json=payload)
        resp.raise_for_status()
        return RuntimeContext.model_validate(resp.json())

    async def process_intent(
        self,
        intent: IntentFrame,
        user_id: str,
        agent_id: str,
    ) -> ExecutionResult:
        payload = {
            "intent": intent.model_dump(mode="json"),
            "user_context": {"user_id": user_id, "agent_id": agent_id},
        }
        resp = await self._client.post("/process", json=payload)
        resp.raise_for_status()
        return ExecutionResult.model_validate(resp.json())

    async def get_audit_log(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/audit")
        resp.raise_for_status()
        return resp.json()

    async def clear_audit_log(self) -> None:
        resp = await self._client.post("/audit/clear")
        resp.raise_for_status()
