"""Vault backend that delegates to the running vault service over UDS.

This backend implements the :class:`CredentialVault` ABC so any consumer
that expects the ABC (e.g. the executor gateway) can transparently talk
to the centralised vault service started by the supervisor.

Auto-registers as ``"service"`` on import::

    from intentframe_credentials.backends import service_backend  # noqa: F401

    vault = create_vault("service")
    value = await vault.get("openai", "api_key")
"""

from __future__ import annotations

import logging

from intentframe_credentials.client import VaultClient
from intentframe_credentials.protocol import CredentialVault, register_backend

logger = logging.getLogger(__name__)


class ServiceVault(CredentialVault):
    """Credential vault backed by the vault HTTP service over UDS.

    All operations are forwarded to the running vault service.  If the
    service is unreachable the error propagates — there is no fallback.
    """

    def __init__(self, socket_path: str | None = None, **_kwargs: object) -> None:
        self._client = VaultClient(socket_path)

    async def get(self, namespace: str, key: str) -> str | None:
        return await self._client.get(namespace, key)

    async def store(self, namespace: str, key: str, value: str) -> None:
        await self._client.store(namespace, key, value)

    async def delete(self, namespace: str, key: str) -> None:
        await self._client.delete(namespace, key)

    async def has(self, namespace: str, key: str) -> bool:
        return await self._client.has(namespace, key)

    async def list_keys(self, namespace: str) -> list[str]:
        summaries = await self._client.list_all()
        return [s.key for s in summaries if s.namespace == namespace]

    async def close(self) -> None:
        await self._client.close()


register_backend("service", ServiceVault)
