"""
Abstract base class for audit logging implementations.

The audit logger records every execution event and every security event.
The audit trail is fully APPEND-ONLY: every row is an INSERT, no row is
ever UPDATEd.  Each entry contains a hash linking it to the previous
entry, forming a tamper-evident chain where every field is protected.

Each execution produces exactly TWO entries:
    1. status=STARTED  -- logged before the adapter runs
    2. status=COMPLETED / FAILED / TIMED_OUT -- logged after

Core Invariant:
    - The audit logger ONLY accepts pre-scrubbed data.
    - Credentials are NEVER written to audit logs.
    - Raw params are NEVER stored -- only their SHA-256 hash.
    - No row is ever modified after insertion (append-only).
    - The hash chain covers EVERY field in EVERY row.

The gateway scrubs all data through CredentialScrubber before passing
it to the audit logger. The logger itself does NOT scrub -- this
separation of concerns means the scrubber can be tested independently.

Implementations to create later:
    - sqlite_audit_logger.py  (default -- SQLite with WAL mode)
    - cloud_audit_logger.py   (cloud -- structured logging to cloud service)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from executor.exceptions import ConfigurationError
from executor.models import AuditEntry, SecurityEvent

if TYPE_CHECKING:
    from executor.config.schema import StorageConfig

__all__ = ["AuditLogger", "register_audit_logger", "create_audit_logger"]

# ─── Plugin Registry ─────────────────────────────────────────────────────────

_AUDIT_REGISTRY: dict[str, type[AuditLogger]] = {}


def register_audit_logger(
    backend: str, logger_class: type[AuditLogger]
) -> None:
    """Register an audit logger implementation for config-driven instantiation."""
    _AUDIT_REGISTRY[backend] = logger_class


def create_audit_logger(config: StorageConfig) -> AuditLogger:
    """Instantiate the configured audit logger from the registry."""
    logger_class = _AUDIT_REGISTRY.get(config.audit_backend)
    if logger_class is None:
        registered = ", ".join(sorted(_AUDIT_REGISTRY)) or "(none)"
        raise ConfigurationError(
            f"Unknown audit backend: '{config.audit_backend}'. "
            f"Registered backends: {registered}",
        )
    return logger_class(db_path=config.database_path or "")


class AuditLogger(ABC):
    """Abstract base for audit log implementations.

    Contract:
        - Every execution produces exactly two events (STARTED + outcome).
        - Both events are INSERTs -- never UPDATEs.
        - Security events are logged independently of executions.
        - All methods are async to support network-based backends.
        - Implementations MUST maintain hash chain integrity.
        - Implementations MUST be safe for concurrent access.
        - If logging fails, the error MUST propagate (fail-closed).
    """

    @abstractmethod
    async def log_event(self, entry: AuditEntry) -> None:
        """Append an immutable audit event to the log.

        Called for BOTH start and completion events.  Each call
        INSERTs a new row; no existing row is ever modified.

        Args:
            entry: Fully populated AuditEntry with hash chain fields.
                   params_hash contains a SHA-256 digest (not raw params).
        """
        ...

    @abstractmethod
    async def log_security_event(self, event: SecurityEvent) -> None:
        """Log a security-relevant event.

        Called for: invalid auth, unknown actions, suspicious patterns,
        rate limit violations, etc. These are stored separately from
        the main audit log for security monitoring and alerting.

        Args:
            event: The security event to record.
        """
        ...

    @abstractmethod
    async def get_entries(self, execution_id: str) -> list[AuditEntry]:
        """Retrieve all audit entries for an execution ID.

        Returns entries in chronological order (STARTED first, then
        COMPLETED/FAILED). Returns empty list if not found.
        """
        ...

    @abstractmethod
    async def verify_chain_integrity(self) -> bool:
        """Verify that the entire audit hash chain is intact.

        Returns True if every entry's hash is valid and the chain
        linkage is correct. False if any entry has been tampered with.
        """
        ...

    def close(self) -> None:
        """Release resources (DB connections, file handles, etc.)."""
