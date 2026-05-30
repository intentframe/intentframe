"""
macOS platform implementations for IntentFrame Executor.

Registers all macOS-specific implementations into the executor's
plugin registries: transport, auth, credential vault, audit logger,
state store, and capability adapters.

Usage:
    from intentframe_executor_pack_macos import register_all
    register_all()

    # Now config-driven startup can create macOS components:
    # transport: unix_socket
    # auth: guardian_hmac
    # credentials: keyring (macOS Keychain)
    # storage: sqlite
    # adapters: files, mail, calendar, etc.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_all() -> None:
    """Register all macOS platform implementations into executor registries.

    Call this once before building the executor gateway.
    Each component registers itself; failures are logged but non-fatal
    (except for core infrastructure).
    """
    _register_transport()
    _register_auth()
    _register_credential_vault()
    _register_storage()
    _register_adapters()
    logger.info("macOS platform registered")


def _register_transport() -> None:
    from .transport import UnixSocketTransport
    from executor_sdk.transport import register_transport

    register_transport("unix_socket", UnixSocketTransport)


def _register_auth() -> None:
    from .auth import GuardianHMACVerifier
    from executor_sdk.auth import register_auth_verifier

    register_auth_verifier("guardian_hmac", GuardianHMACVerifier)


def _register_credential_vault() -> None:
    from .credential_vault import KeychainVault
    from executor_sdk.services.credential_vault import register_credential_vault

    # The SDK already auto-registers all backends (keyring/env/hashicorp/
    # service) on import.  We re-assert "keyring" here to document that the
    # macOS platform's credential store is the OS Keychain.
    register_credential_vault("keyring", KeychainVault)


def _register_storage() -> None:
    from .audit_logger import SQLiteAuditLogger
    from .state_store import SQLiteStateStore
    from executor_sdk.services.audit_logger import register_audit_logger
    from executor_sdk.services.state_store import register_state_store

    register_audit_logger("sqlite", SQLiteAuditLogger)
    register_state_store("sqlite", SQLiteStateStore)


def _register_adapters() -> None:
    from .adapters import register_all_adapters

    register_all_adapters()
