"""Exception hierarchy for the credential vault.

All vault exceptions inherit from VaultError so callers can
catch broadly or handle specific failures precisely.
"""

from __future__ import annotations


class VaultError(Exception):
    """Base exception for all credential vault errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class CredentialNotFoundError(VaultError):
    """Requested credential does not exist in any backend."""


class CredentialStoreError(VaultError):
    """Failed to persist a credential to the backend."""


class CredentialDeleteError(VaultError):
    """Failed to remove a credential from the backend."""


class ValidationFailedError(VaultError):
    """A credential test/validation check failed.

    The credential was syntactically stored but the external service
    rejected it (bad IMAP password, invalid API key, etc.).
    """


class BackendUnavailableError(VaultError):
    """The configured backend (keyring, vault service, etc.) is unreachable."""


class MetadataStoreError(VaultError):
    """Failed to read/write the metadata SQLite database."""
