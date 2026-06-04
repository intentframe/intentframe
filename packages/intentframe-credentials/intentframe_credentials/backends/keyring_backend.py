"""Cross-platform OS keyring backend.

Uses the ``keyring`` library which auto-detects the correct backend:
    - macOS:   Keychain (AES-256, tied to user login)
    - Windows: Credential Manager (DPAPI)
    - Linux:   Secret Service (GNOME Keyring / KDE Wallet)

All keyring calls are dispatched via ``asyncio.to_thread`` because the
library is synchronous and may block on OS-level dialogs.
"""

from __future__ import annotations

import asyncio
import logging

from intentframe_credentials.exceptions import BackendUnavailableError
from intentframe_credentials.protocol import CredentialVault, register_backend

logger = logging.getLogger(__name__)

SERVICE_PREFIX = "com.intentframe.vault"


class KeyringVault(CredentialVault):
    """OS keyring credential vault.

    Credentials are stored under the service name
    ``com.intentframe.vault.<namespace>`` with the *key* used as the
    keyring "username" field.
    """

    def __init__(self, **_kwargs: object) -> None:
        try:
            import keyring as _keyring

            self._keyring = _keyring
        except ImportError as exc:
            raise BackendUnavailableError(
                "keyring package required. Install with: pip install keyring"
            ) from exc

    # -- helpers --

    @staticmethod
    def _service_name(namespace: str) -> str:
        """Translate a vault namespace to a keyring service name.

        e.g. ``"email.user@gmail.com"`` →
        ``"com.intentframe.vault.email.user@gmail.com"``
        """
        return f"{SERVICE_PREFIX}.{namespace}"

    # -- CredentialVault interface --

    async def get(self, namespace: str, key: str) -> str | None:
        service = self._service_name(namespace)
        return await asyncio.to_thread(self._keyring.get_password, service, key)

    async def store(self, namespace: str, key: str, value: str) -> None:
        service = self._service_name(namespace)
        await asyncio.to_thread(self._keyring.set_password, service, key, value)
        logger.debug("stored credential: namespace=%s key=%s", namespace, key)

    async def delete(self, namespace: str, key: str) -> None:
        service = self._service_name(namespace)
        try:
            await asyncio.to_thread(self._keyring.delete_password, service, key)
            logger.debug("deleted credential: namespace=%s key=%s", namespace, key)
        except self._keyring.errors.PasswordDeleteError:
            logger.debug(
                "credential already absent: namespace=%s key=%s", namespace, key,
            )

    async def has(self, namespace: str, key: str) -> bool:
        return (await self.get(namespace, key)) is not None

    async def list_keys(self, namespace: str) -> list[str]:
        # keyring has no native "list" API.  This is backed by the
        # metadata DB at the service layer.  A bare KeyringVault used
        # without the metadata store returns an empty list.
        return []


# Auto-register on import
register_backend("keyring", KeyringVault)
