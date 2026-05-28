"""
macOS platform implementations for IntentFrame Executor.

Registers all macOS-specific implementations into the executor's
plugin registries: transport, auth, credential vault, audit logger,
state store, and capability adapters.

Usage:
    from executor.platforms.macos import register_all
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
    from executor.platforms.macos.transport import UnixSocketTransport
    from executor.transport import register_transport

    register_transport("unix_socket", UnixSocketTransport)


def _register_auth() -> None:
    from executor.platforms.macos.auth import GuardianHMACVerifier
    from executor.auth import register_auth_verifier

    register_auth_verifier("guardian_hmac", GuardianHMACVerifier)


def _register_credential_vault() -> None:
    from executor.platforms.macos.credential_vault import KeychainVault
    from executor.services.credential_vault import register_credential_vault

    register_credential_vault("keyring", KeychainVault)
    # "service" backend is auto-registered by the import in
    # executor.services.credential_vault (service_backend module-level call)


def _register_storage() -> None:
    from executor.platforms.macos.audit_logger import SQLiteAuditLogger
    from executor.platforms.macos.state_store import SQLiteStateStore
    from executor.services.audit_logger import register_audit_logger
    from executor.services.state_store import register_state_store

    register_audit_logger("sqlite", SQLiteAuditLogger)
    register_state_store("sqlite", SQLiteStateStore)


def _register_adapters() -> None:
    from executor.platforms.macos.adapters import register_all_adapters

    register_all_adapters()
