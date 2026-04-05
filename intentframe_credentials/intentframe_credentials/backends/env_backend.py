"""Environment-variable credential backend for development and testing.

Reads secrets from ``os.environ`` and an optional in-memory overlay.
Writes go to the in-memory overlay only — nothing is persisted.

This is intentionally *not* secure.  It exists so that:
    - CI pipelines can inject secrets via env vars
    - Unit tests can pre-populate credentials without touching keyring
    - Dev machines work without keyring configured
"""

from __future__ import annotations

import os
from collections import defaultdict

from intentframe_credentials.protocol import CredentialVault, register_backend

__all__ = ["EnvVault"]


class EnvVault(CredentialVault):
    """Read credentials from env vars (and an in-memory write layer).

    Look-up order for ``get(namespace, key)``:

    1. In-memory overlay (populated by ``store``).
    2. Environment variable ``<NAMESPACE>_<KEY>`` (upper-cased, ``/``
       and ``.`` replaced with ``_``).

    Example: ``get("openai", "api_key")`` checks the overlay first,
    then falls back to ``os.environ["OPENAI_API_KEY"]``.
    """

    def __init__(self, **_kwargs: object) -> None:
        self._store: dict[str, dict[str, str]] = defaultdict(dict)

    # -- helpers --

    @staticmethod
    def _env_key(namespace: str, key: str) -> str:
        """Build an env-var name from namespace + key."""
        raw = f"{namespace}_{key}"
        return raw.upper().replace("/", "_").replace(".", "_").replace("-", "_")

    # -- CredentialVault interface --

    async def get(self, namespace: str, key: str) -> str | None:
        if key in self._store.get(namespace, {}):
            return self._store[namespace][key]
        return os.environ.get(self._env_key(namespace, key))

    async def store(self, namespace: str, key: str, value: str) -> None:
        self._store[namespace][key] = value

    async def delete(self, namespace: str, key: str) -> None:
        self._store.get(namespace, {}).pop(key, None)

    async def has(self, namespace: str, key: str) -> bool:
        return (await self.get(namespace, key)) is not None

    async def list_keys(self, namespace: str) -> list[str]:
        return list(self._store.get(namespace, {}).keys())


register_backend("env", EnvVault)
