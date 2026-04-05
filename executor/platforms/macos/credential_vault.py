"""
macOS Keychain credential vault — re-exported from ``intentframe_credentials``.

Executor code and the platform registration in ``__init__.py`` continue
to import ``KeychainVault`` from this module unchanged.
"""

from intentframe_credentials.backends.keyring_backend import KeyringVault as KeychainVault

__all__ = ["KeychainVault"]
