"""
macOS Keychain credential vault.

The macOS platform stores secrets in the OS keyring (Keychain). The concrete
backend lives in ``intentframe_credentials``, but the pack sources it through
``executor_sdk`` so packs never depend on the credentials package directly —
the SDK auto-imports and re-exports all backends underneath.

Executor code and the platform registration in ``__init__.py`` continue to
import ``KeychainVault`` from this module unchanged.
"""

from executor_sdk.services.credential_vault import KeyringVault as KeychainVault

__all__ = ["KeychainVault"]
