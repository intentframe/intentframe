"""
Credential vault — re-exported from the shared ``intentframe_credentials`` package.

All executor code continues to import from this module unchanged::

    from executor_sdk.services.credential_vault import CredentialVault
    from executor_sdk.services.credential_vault import create_credential_vault

Under the hood everything is now backed by ``intentframe_credentials``.
"""

from __future__ import annotations

from typing import Any

from intentframe_credentials.backends import service_backend as _sb  # noqa: F401 — registers "service"
from intentframe_credentials.protocol import (
    CredentialVault,
    create_vault,
    register_backend as register_credential_vault,
)

from executor_sdk.exceptions import ConfigurationError

__all__ = ["CredentialVault", "register_credential_vault", "create_credential_vault"]


def create_credential_vault(config: Any) -> CredentialVault:
    """Instantiate the configured credential vault from the registry.

    Adapts the executor-specific ``CredentialConfig`` to the shared
    ``create_vault(backend, **options)`` interface.

    Raises:
        ConfigurationError: If the backend is not registered.
    """
    try:
        return create_vault(backend=config.backend, **config.options)
    except Exception as exc:
        raise ConfigurationError(str(exc)) from exc
