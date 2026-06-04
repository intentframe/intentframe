"""
Credential vault — re-exported from the shared ``intentframe_credentials`` package.

All executor code continues to import from this module unchanged::

    from executor_sdk.services.credential_vault import CredentialVault
    from executor_sdk.services.credential_vault import create_credential_vault

Under the hood everything is now backed by ``intentframe_credentials``.
"""

from __future__ import annotations

from typing import Any

# Auto-register every storage backend so config-driven startup can select any
# of them by name (keyring / env / hashicorp / service) and so platform packs
# never have to import ``intentframe_credentials`` directly — they get what
# they need from the SDK.  Each backend module self-registers on import; the
# concrete classes are re-exported below for packs that reference them.
#
# Importing ``hashicorp_backend`` is safe without the optional ``hvac`` package
# installed: the module only registers the class, and ``hvac`` is imported
# lazily inside ``HashiCorpVault`` when (and if) it is instantiated.
from intentframe_credentials.backends import (  # noqa: F401 — import side effects register backends
    env_backend as _env_backend,
    hashicorp_backend as _hashicorp_backend,
    keyring_backend as _keyring_backend,
    service_backend as _service_backend,
)
from intentframe_credentials.backends.env_backend import EnvVault
from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
from intentframe_credentials.backends.keyring_backend import KeyringVault
from intentframe_credentials.backends.service_backend import ServiceVault
from intentframe_credentials.protocol import (
    CredentialVault,
    create_vault,
    register_backend as register_credential_vault,
)

from executor_sdk.exceptions import ConfigurationError

__all__ = [
    "CredentialVault",
    "EnvVault",
    "HashiCorpVault",
    "KeyringVault",
    "ServiceVault",
    "register_credential_vault",
    "create_credential_vault",
]


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
