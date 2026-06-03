"""
Exception hierarchy for the IntentFrame Executor.

Every exception in the executor inherits from ExecutorError.
This allows callers to catch all executor-related errors with a single
except clause while still being able to handle specific errors precisely.

Design principle: exceptions carry enough context for the gateway to
construct a meaningful ExecutionResult(success=False, error=...) without
leaking internal details or credentials.
"""

from __future__ import annotations


class ExecutorError(Exception):
    """Base exception for all executor errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


# ═══════════════════════════════════════════════════════════════════════════════
# Protocol Boundary Errors
# ═══════════════════════════════════════════════════════════════════════════════


class AuthenticationError(ExecutorError):
    """Authorization proof is invalid, expired, or missing.

    Raised by AuthVerifier implementations when the proof
    attached to an ExecutionRequest fails verification.
    Always results in immediate rejection + security event log.
    """


class RequestValidationError(ExecutorError):
    """Request schema is invalid (missing fields, wrong types, etc.).

    Raised during Pydantic validation of the inbound ExecutionRequest.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Adapter / Execution Errors
# ═══════════════════════════════════════════════════════════════════════════════


class AdapterError(ExecutorError):
    """A capability adapter failed during execution.

    Wraps any exception raised inside an adapter's execute() method.
    The gateway catches this and returns ExecutionResult(success=False).
    """

    def __init__(
        self,
        message: str,
        *,
        adapter_id: str = "",
        action: str = "",
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.adapter_id = adapter_id
        self.action = action


class AdapterTimeoutError(AdapterError):
    """Adapter did not respond within the configured timeout.

    The gateway enforces timeout via asyncio.wait_for().
    This exception is raised when the timeout expires.
    """


class AdapterNotFoundError(ExecutorError):
    """No adapter registered for the requested action type.

    Raised by the dispatcher when action_type doesn't map
    to any registered CapabilityAdapter.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Service Errors
# ═══════════════════════════════════════════════════════════════════════════════


class CredentialError(ExecutorError):
    """Failed to access or retrieve credentials from the vault.

    Raised by CredentialVault implementations. The executor
    must NOT proceed with execution when credentials are unavailable.
    """


class AuditError(ExecutorError):
    """Failed to write to the audit log.

    This is a critical failure. The executor must NOT proceed
    with execution if audit logging fails (fail-closed).
    """


class StateStoreError(ExecutorError):
    """Failed to read/write execution state or rollback data."""


class VirtualFileSystemError(ExecutorError):
    """Error in virtual filesystem operations (path resolution, mount lookup, etc.)."""


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration Errors
# ═══════════════════════════════════════════════════════════════════════════════


class ConfigurationError(ExecutorError):
    """Invalid or missing configuration.

    Raised during startup if executor.yaml is invalid or
    if a required component cannot be instantiated from config.
    """
