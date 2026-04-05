"""HTTP client for the IntentFrame gateway over Unix domain socket.

Every method maps to a gateway API endpoint.  The CLI never talks
to individual services directly — all communication goes through
the gateway's single UDS.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

import httpx


def _default_socket() -> str:
    run_dir = os.environ.get(
        "INTENTFRAME_RUN_DIR",
        os.path.expanduser("~/.intentframe/run"),
    )
    return os.path.join(run_dir, "gateway.sock")


class GatewayClient:
    """Async wrapper around the gateway's HTTP-over-UDS API."""

    def __init__(self, socket_path: str | None = None) -> None:
        self._socket = socket_path or _default_socket()
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            transport = httpx.AsyncHTTPTransport(uds=self._socket)
            self._client = httpx.AsyncClient(
                transport=transport,
                base_url="http://gateway",
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @property
    def socket_path(self) -> str:
        return self._socket

    @property
    def socket_exists(self) -> bool:
        return Path(self._socket).exists()

    # ── Generic ───────────────────────────────────────────────────

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        c = await self._ensure_client()
        return await c.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        c = await self._ensure_client()
        return await c.post(path, **kwargs)

    # ── System ────────────────────────────────────────────────────

    async def health(self) -> dict:
        r = await self.get("/system/health")
        return r.json()

    async def services(self) -> list[dict]:
        r = await self.get("/system/services")
        return r.json().get("services", [])

    async def shutdown(self) -> dict:
        r = await self.post("/system/shutdown")
        return r.json()

    async def credential_status(self) -> dict:
        r = await self.get("/system/credential-status")
        return r.json()

    async def bootstrap(self) -> dict:
        r = await self.post("/system/bootstrap")
        return r.json()

    async def service_start(self, name: str) -> dict:
        r = await self.post(f"/system/{name}/start")
        return r.json()

    async def service_stop(self, name: str) -> dict:
        r = await self.post(f"/system/{name}/stop")
        return r.json()

    async def service_restart(self, name: str) -> dict:
        r = await self.post(f"/system/{name}/restart")
        return r.json()

    async def logs(self, service: str, lines: int = 50) -> dict:
        r = await self.get(f"/system/logs/{service}", params={"lines": lines})
        return r.json()

    async def log_stream(self, service: str) -> AsyncIterator[str]:
        """Stream log lines via SSE. Yields raw line text."""
        c = await self._ensure_client()
        async with c.stream(
            "GET", f"/system/logs/{service}/stream"
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    yield line[5:].strip()

    # ── Jarvis ────────────────────────────────────────────────────

    async def chat(self, message: str) -> dict:
        r = await self.post("/jarvis/chat", json={"message": message})
        return r.json()

    async def chat_stream(self, message: str) -> AsyncIterator[str]:
        """Stream Jarvis response chunks via SSE."""
        c = await self._ensure_client()
        async with c.stream(
            "POST", "/jarvis/chat/stream", json={"message": message}
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    yield line[5:].strip()

    async def jarvis_status(self) -> dict:
        r = await self.get("/jarvis/status")
        return r.json()

    async def jarvis_session(self) -> dict:
        r = await self.get("/jarvis/session")
        return r.json()

    # ── Platform ──────────────────────────────────────────────────

    async def platform_health(self) -> dict:
        r = await self.get("/platform/health")
        return r.json()

    async def permissions(self) -> dict:
        r = await self.get("/platform/permissions")
        return r.json()

    # ── Audit ─────────────────────────────────────────────────────

    async def audit(self) -> list:
        r = await self.get("/audit/")
        return r.json()

    # ── Policies ──────────────────────────────────────────────────

    async def policies(self) -> dict:
        r = await self.get("/policies/")
        return r.json()

    # ── Vault ─────────────────────────────────────────────────────

    async def vault_health(self) -> dict:
        r = await self.get("/vault/health")
        return r.json()

    async def vault_list(self, namespace: str | None = None) -> list[dict]:
        path = f"/vault/v1/credentials/{namespace}" if namespace else "/vault/v1/credentials"
        r = await self.get(path)
        return r.json()

    async def vault_get(self, namespace: str, key: str) -> dict:
        r = await self.get(f"/vault/v1/credentials/{namespace}/{key}")
        r.raise_for_status()
        return r.json()

    async def vault_set(
        self,
        namespace: str,
        key: str,
        value: str,
        *,
        delivery_mode: str = "executor_only",
        env_name: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"value": value, "delivery_mode": delivery_mode}
        if env_name:
            body["env_name"] = env_name
        c = await self._ensure_client()
        r = await c.put(f"/vault/v1/credentials/{namespace}/{key}", json=body)
        r.raise_for_status()
        return r.json()

    async def vault_delete(self, namespace: str, key: str) -> dict:
        c = await self._ensure_client()
        r = await c.delete(f"/vault/v1/credentials/{namespace}/{key}")
        r.raise_for_status()
        return r.json()

    async def vault_has(self, namespace: str, key: str) -> bool:
        c = await self._ensure_client()
        r = await c.head(f"/vault/v1/credentials/{namespace}/{key}")
        return r.status_code == 200

    # ── EDI ───────────────────────────────────────────────────────

    async def edi_accounts(self) -> dict:
        r = await self.get("/edi/accounts")
        return r.json()

    async def edi_add_account(
        self, email: str, display_name: str = "", validate: bool = True
    ) -> dict:
        r = await self.post(
            "/edi/accounts",
            json={"email": email, "display_name": display_name, "validate_imap": validate},
        )
        r.raise_for_status()
        return r.json()

    async def edi_remove_account(self, email: str) -> dict:
        c = await self._ensure_client()
        r = await c.delete(f"/edi/accounts/{email}")
        r.raise_for_status()
        return r.json()

    async def edi_status(self) -> dict:
        r = await self.get("/edi/status")
        return r.json()

    # ── Config ────────────────────────────────────────────────────

    async def config_list(self) -> dict:
        r = await self.get("/config/")
        return r.json()

    async def config_get(self, key: str) -> dict:
        r = await self.get(f"/config/{key}")
        return r.json()

    async def config_set(self, key: str, value: Any) -> dict:
        c = await self._ensure_client()
        r = await c.put(f"/config/{key}", json={"value": value})
        r.raise_for_status()
        return r.json()

    async def config_delete(self, key: str) -> dict:
        c = await self._ensure_client()
        r = await c.delete(f"/config/{key}")
        r.raise_for_status()
        return r.json()

    # ── System Config Env ────────────────────────────────────────

    async def config_env_list(self) -> dict:
        r = await self.get("/system/config-env")
        return r.json()

    async def config_env_set(self, key: str, value: str) -> dict:
        c = await self._ensure_client()
        r = await c.put("/system/config-env", json={"key": key, "value": value})
        r.raise_for_status()
        return r.json()

    async def config_env_delete(self, key: str) -> dict:
        c = await self._ensure_client()
        r = await c.delete(f"/system/config-env/{key}")
        r.raise_for_status()
        return r.json()
