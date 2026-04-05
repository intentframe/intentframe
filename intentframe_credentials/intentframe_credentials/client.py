"""Async and sync clients for the credential vault service.

The *only* transport is HTTP over a Unix Domain Socket (UDS).  There is
no fallback — if the vault service is not running, calls fail loudly.
The supervisor is responsible for starting the vault before any module
that needs credentials.  Modules that only need ``runtime_env``
credentials read them from ``os.environ`` (injected by the supervisor).

Usage::

    # Async (preferred — supervisor, dashboard, executor)
    from intentframe_credentials.client import VaultClient

    async with VaultClient() as vault:
        key = await vault.get("openai", "api_key")

    # Sync wrapper (CLI tools, one-off scripts)
    from intentframe_credentials.client import VaultClientSync

    vault = VaultClientSync()
    key = vault.get("openai", "api_key")
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from intentframe_credentials.models import DeliveryMode, MaskedSummary

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET = Path("~/.intentframe/run/credential-vault.sock")

_BASE_URL = "http://credential-vault"


class VaultClient:
    """Async credential vault client over UDS.

    All requests go to the vault service.  If the service is unreachable
    the error propagates — there is no silent fallback.
    """

    def __init__(self, socket_path: str | Path | None = None) -> None:
        raw = socket_path or os.environ.get(
            "INTENTFRAME_VAULT_SOCKET", str(_DEFAULT_SOCKET),
        )
        self._socket_path = Path(raw).expanduser()
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            transport = httpx.AsyncHTTPTransport(uds=str(self._socket_path))
            self._http = httpx.AsyncClient(
                transport=transport,
                base_url=_BASE_URL,
                timeout=10.0,
            )
        return self._http

    # ── Context manager ──────────────────────────────────────────────────

    async def __aenter__(self) -> VaultClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ── Core operations ──────────────────────────────────────────────────

    async def get(self, namespace: str, key: str) -> str | None:
        """Retrieve a credential value.  Returns ``None`` if not found."""
        client = await self._client()
        r = await client.get(f"/v1/credentials/{namespace}/{key}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()["value"]

    async def store(
        self,
        namespace: str,
        key: str,
        value: str,
        *,
        delivery_mode: DeliveryMode = DeliveryMode.EXECUTOR_ONLY,
        allowed_consumers: list[str] | None = None,
        env_name: str | None = None,
        validator_id: str | None = None,
    ) -> None:
        """Store a credential.  Never returns the value."""
        body: dict[str, Any] = {
            "value": value,
            "delivery_mode": delivery_mode.value,
            "allowed_consumers": allowed_consumers or [],
        }
        if env_name:
            body["env_name"] = env_name
        if validator_id:
            body["validator_id"] = validator_id

        client = await self._client()
        r = await client.put(
            f"/v1/credentials/{namespace}/{key}",
            json=body,
        )
        r.raise_for_status()

    async def delete(self, namespace: str, key: str) -> None:
        """Delete a credential."""
        client = await self._client()
        r = await client.delete(f"/v1/credentials/{namespace}/{key}")
        r.raise_for_status()

    async def has(self, namespace: str, key: str) -> bool:
        """Check if a credential exists."""
        client = await self._client()
        r = await client.head(f"/v1/credentials/{namespace}/{key}")
        return r.status_code == 200

    async def list_all(self) -> list[MaskedSummary]:
        """List masked summaries for every credential."""
        client = await self._client()
        r = await client.get("/v1/credentials")
        r.raise_for_status()
        return [MaskedSummary(**item) for item in r.json()]

    async def list_runtime_env(self) -> list[dict[str, Any]]:
        """Return runtime_env credential metadata (for supervisor spawn)."""
        client = await self._client()
        r = await client.get("/v1/runtime-env")
        r.raise_for_status()
        return r.json()


# ── Synchronous wrapper ──────────────────────────────────────────────────────


class VaultClientSync:
    """Thin synchronous wrapper around :class:`VaultClient`.

    Designed for non-async callers (CLI tools, one-off scripts).
    Each method creates a short-lived event loop via ``asyncio.run``.
    """

    def __init__(self, socket_path: str | Path | None = None) -> None:
        self._socket_path = socket_path

    def _run(self, coro):  # noqa: ANN001, ANN202
        return asyncio.run(coro)

    def get(self, namespace: str, key: str) -> str | None:
        async def _do():
            async with VaultClient(self._socket_path) as c:
                return await c.get(namespace, key)
        return self._run(_do())

    def store(
        self,
        namespace: str,
        key: str,
        value: str,
        *,
        delivery_mode: DeliveryMode = DeliveryMode.EXECUTOR_ONLY,
        allowed_consumers: list[str] | None = None,
        env_name: str | None = None,
        validator_id: str | None = None,
    ) -> None:
        async def _do():
            async with VaultClient(self._socket_path) as c:
                await c.store(
                    namespace, key, value,
                    delivery_mode=delivery_mode,
                    allowed_consumers=allowed_consumers,
                    env_name=env_name,
                    validator_id=validator_id,
                )
        self._run(_do())

    def delete(self, namespace: str, key: str) -> None:
        async def _do():
            async with VaultClient(self._socket_path) as c:
                await c.delete(namespace, key)
        self._run(_do())

    def has(self, namespace: str, key: str) -> bool:
        async def _do():
            async with VaultClient(self._socket_path) as c:
                return await c.has(namespace, key)
        return self._run(_do())
