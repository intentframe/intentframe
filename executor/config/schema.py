"""
Pydantic schema for executor.yaml configuration.

Every configurable aspect of the executor is represented here.
The schema provides:
    - Type validation (catch typos at startup, not at 3am)
    - Default values (sensible defaults for common deployments)
    - Documentation (field descriptions serve as config docs)

The config is intentionally flat where possible. Nesting is used
only for logical grouping (transport, auth, etc.), not for
hierarchy's sake.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from executor_sdk.constants import (
    DEFAULT_ADAPTER_TIMEOUT,
    DEFAULT_GRPC_PORT,
    DEFAULT_MAX_WORKERS,
    DEFAULT_REST_PORT,
    DEFAULT_UNIX_SOCKET_PATH,
)

__all__ = [
    "ExecutorConfig",
    "TransportConfig",
    "AuthConfig",
    "CredentialConfig",
    "WorkerPoolConfig",
    "AdapterConfig",
    "StorageConfig",
    "LoggingConfig",
]


class TransportConfig(BaseModel):
    """Configuration for the transport layer.

    Only ONE transport is active per executor instance.

    Types:
        unix_socket: Local IPC (device default)
        grpc: Cross-machine, high-performance
        rest: Admin tools, debugging, broad compatibility
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        default="unix_socket",
        description="Transport type: unix_socket, grpc, rest",
    )
    options: dict[str, Any] = Field(
        default_factory=lambda: {"socket_path": DEFAULT_UNIX_SOCKET_PATH},
        description="Transport-specific configuration options",
    )


class AuthConfig(BaseModel):
    """Configuration for authorization verification.

    Only ONE auth verifier is active per executor instance.

    Types:
        guardian_hmac: IntentFrame default (HMAC signature from Guardian)
        mtls: Mutual TLS certificate verification (cloud)
        bearer: JWT or opaque bearer token (admin/CI)
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        default="guardian_hmac",
        description="Auth verifier type: guardian_hmac, mtls, bearer",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Auth-specific configuration options",
    )


class CredentialConfig(BaseModel):
    """Configuration for the credential vault backend.

    Backends:
        service: Vault service over UDS (default — uses the supervisor-managed vault)
        keyring: OS native keyring directly (macOS Keychain, Windows Credential Locker)
        env: Environment variables (development/testing ONLY)
    """

    model_config = ConfigDict(extra="forbid")

    backend: str = Field(
        default="service",
        description="Credential backend: service, keyring, env",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Backend-specific configuration options",
    )


class WorkerPoolConfig(BaseModel):
    """Configuration for the capability worker pool."""

    model_config = ConfigDict(extra="forbid")

    max_workers: int = Field(
        default=DEFAULT_MAX_WORKERS,
        ge=1,
        le=32,
        description="Maximum concurrent adapter executions",
    )
    default_timeout_seconds: float = Field(
        default=DEFAULT_ADAPTER_TIMEOUT,
        gt=0,
        description="Default timeout per adapter execution (seconds)",
    )


class AdapterConfig(BaseModel):
    """Configuration for capability adapters.

    The enabled list determines which adapters are loaded at startup.
    Each adapter ID must be registered via register_adapter() by
    a platform-specific module.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(
        default_factory=list,
        description="List of adapter IDs to load at startup",
    )


class StorageConfig(BaseModel):
    """Configuration for database, log file paths, and backend selection.

    If paths are null/None, platform-specific defaults are used:
        macOS:  ~/Library/Application Support/IntentFrame/
        Linux:  ~/.local/share/intentframe/
        Cloud:  /var/lib/intentframe/
    """

    model_config = ConfigDict(extra="forbid")

    audit_backend: str = Field(
        default="sqlite",
        description="Audit log backend: sqlite, cloud",
    )
    state_backend: str = Field(
        default="sqlite",
        description="State store backend: sqlite, redis",
    )
    database_path: str | None = Field(
        default=None,
        description="Path to SQLite database. None = platform default.",
    )
    log_path: str | None = Field(
        default=None,
        description="Path to log file. None = platform default.",
    )


class LoggingConfig(BaseModel):
    """Configuration for structured logging."""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    format: str = Field(
        default="json",
        description="Log format: json (structured) or console (human-readable)",
    )


class ExecutorConfig(BaseModel):
    """Root configuration schema for the IntentFrame Executor.

    Loaded from executor.yaml and validated at startup.
    Any validation error prevents the executor from starting (fail-closed).
    """

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(
        default="auto",
        description=(
            "Platform to register: 'macos', 'linux', or 'auto' (detect from OS). "
            "Determines which auth verifiers, storage backends, and adapters "
            "are available for the component configs below."
        ),
    )
    transport: TransportConfig = Field(default_factory=TransportConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    credentials: CredentialConfig = Field(default_factory=CredentialConfig)
    worker_pool: WorkerPoolConfig = Field(default_factory=WorkerPoolConfig)
    adapters: AdapterConfig = Field(default_factory=AdapterConfig)
    pack_options: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Opaque executor-pack/adaptor options keyed by pack-owned feature "
            "or adapter ID. Core validates only that each slice is a mapping; "
            "packs own their own schema validation."
        ),
    )
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
