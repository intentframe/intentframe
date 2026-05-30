"""
POSIX executor pack -- portable implementations for IntentFrame Executor.

This is the deployment-neutral base pack. It registers implementations that
rely only on the Python standard library and POSIX semantics, so it runs
identically on Linux, containers, cloud hosts, and macOS:

    transport:   unix_socket   (asyncio UDS, length-prefixed JSON)
    auth:        guardian_hmac (HMAC-SHA256 verifier)
    storage:     sqlite        (append-only audit log + state store)
    adapters:    files         (virtual filesystem)

Credential backends (service / hashicorp / env / keyring) self-register in
``executor_sdk`` on import, so this pack does not register any -- the deployment
selects one via ``credentials.backend`` in executor.yaml.

Platform packs (e.g. intentframe_executor_pack_macos) layer native adapters and
OS-specific backends on top of this base.

Usage:
    from intentframe_executor_pack_posix import register_all
    register_all()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["register_all"]


def register_all() -> None:
    """Register all portable POSIX implementations into executor registries.

    Idempotent: safe to call more than once (registries are keyed dicts).
    """
    _register_transport()
    _register_auth()
    _register_storage()
    _register_adapters()
    logger.info("POSIX executor pack registered")


def _register_transport() -> None:
    from executor_sdk.transport import register_transport
    from intentframe_executor_pack_posix.transport import UnixSocketTransport

    register_transport("unix_socket", UnixSocketTransport)


def _register_auth() -> None:
    from executor_sdk.auth import register_auth_verifier
    from intentframe_executor_pack_posix.auth import GuardianHMACVerifier

    register_auth_verifier("guardian_hmac", GuardianHMACVerifier)


def _register_storage() -> None:
    from executor_sdk.services.audit_logger import register_audit_logger
    from executor_sdk.services.state_store import register_state_store
    from intentframe_executor_pack_posix.audit_logger import SQLiteAuditLogger
    from intentframe_executor_pack_posix.state_store import SQLiteStateStore

    register_audit_logger("sqlite", SQLiteAuditLogger)
    register_state_store("sqlite", SQLiteStateStore)


def _register_adapters() -> None:
    from intentframe_executor_pack_posix.adapters import register_all_adapters

    register_all_adapters()
