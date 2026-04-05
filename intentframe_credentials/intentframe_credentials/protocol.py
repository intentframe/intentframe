"""Abstract credential vault contract and backend registry.

Extracted from ``executor/services/credential_vault.py`` to be shared
across all IntentFrame modules (executor, EDI, supervisor, dashboard).

The ABC defines the minimal storage interface.  Concrete backends
(keyring, env, future HashiCorp Vault) register themselves via
``register_backend`` and are instantiated with ``create_vault``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from intentframe_credentials.exceptions import VaultError

__all__ = [
    "CredentialVault",
    "register_backend",
    "create_vault",
]

# ── Plugin Registry ──────────────────────────────────────────────────────────

_BACKEND_REGISTRY: dict[str, type[CredentialVault]] = {}


def register_backend(name: str, cls: type[CredentialVault]) -> None:
    """Register a vault backend implementation.

    Platform modules call this at import time::

        register_backend("keyring", KeyringVault)
    """
    _BACKEND_REGISTRY[name] = cls


def create_vault(backend: str, **options: object) -> CredentialVault:
    """Instantiate the named backend from the registry.

    Raises ``VaultError`` if the backend is not registered.
    """
    cls = _BACKEND_REGISTRY.get(backend)
    if cls is None:
        registered = ", ".join(sorted(_BACKEND_REGISTRY)) or "(none)"
        raise VaultError(
            f"Unknown credential backend: '{backend}'. "
            f"Registered: {registered}",
        )
    return cls(**options)


def registered_backends() -> list[str]:
    """Return names of all registered backends."""
    return sorted(_BACKEND_REGISTRY)


# ── Abstract Base Class ──────────────────────────────────────────────────────


class CredentialVault(ABC):
    """Async storage interface for secrets.

    Contract:
        - ``get`` returns the secret value or ``None``.
        - ``store`` persists a secret (upsert semantics).
        - ``delete`` removes a secret (no-op if missing).
        - ``has`` checks existence without fetching the value.
        - ``list_keys`` returns key names within a namespace.
        - Implementations MUST NOT log or expose secret values.
        - All methods are async to support network backends.
    """

    @abstractmethod
    async def get(self, namespace: str, key: str) -> str | None:
        """Retrieve a credential value, or ``None`` if not found."""
        ...

    @abstractmethod
    async def store(self, namespace: str, key: str, value: str) -> None:
        """Persist a credential (creates or overwrites)."""
        ...

    @abstractmethod
    async def delete(self, namespace: str, key: str) -> None:
        """Remove a credential.  No-op if it does not exist."""
        ...

    @abstractmethod
    async def has(self, namespace: str, key: str) -> bool:
        """Check whether a credential exists without retrieving it."""
        ...

    @abstractmethod
    async def list_keys(self, namespace: str) -> list[str]:
        """Return all key names stored under *namespace*."""
        ...
