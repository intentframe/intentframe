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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from executor.constants import (
    DEFAULT_ADAPTER_TIMEOUT,
    DEFAULT_GRPC_PORT,
    DEFAULT_MAX_WORKERS,
    DEFAULT_REST_PORT,
    DEFAULT_UNIX_SOCKET_PATH,
)

# ``resource_registry.floor`` transitively imports ``executor.sandbox.venv``
# which imports ``SandboxConfig`` from this very module.  To break the
# circular import we defer the canonicalize import to the field validator
# body — by the time the validator runs, both modules are fully loaded.

__all__ = [
    "ExecutorConfig",
    "TransportConfig",
    "AuthConfig",
    "CredentialConfig",
    "WorkerPoolConfig",
    "AdapterConfig",
    "HostFilesConfig",
    "SandboxConfig",
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


class MountConfig(BaseModel):
    """Configuration for a single virtual-to-real path mapping."""

    model_config = ConfigDict(extra="forbid")

    virtual_path: str
    real_path: str
    writable: bool = False
    file_filter: str | None = None


class FilesystemConfig(BaseModel):
    """Configuration for the virtual filesystem."""

    model_config = ConfigDict(extra="forbid")

    base_path: str | None = Field(
        default=None,
        description="Base path for resolving relative mount paths. None = home dir.",
    )
    mounts: list[MountConfig] = Field(
        default_factory=list,
        description="Virtual-to-real path mount points.",
    )


class HostFilesConfig(BaseModel):
    """Configuration for the HOST_FILE action family.

    The HOST_FILE adapter operates on real host filesystem paths rather
    than virtual-filesystem paths.  These allowlists are the executor-
    side ceiling — the per-action policy constraints
    (``HostFileConstraints.allowed_host_paths``) ride alongside and
    must not grant paths that this config denies.

    Both lists are normalized at load time via
    :func:`resource_registry.floor.canonicalize_real_path` so that a
    YAML-supplied ``~/Documents`` and a runtime-supplied
    ``/Users/<me>/Documents`` compare as the same path.

    These entries are executor-side *scope roots*, not policy-style
    glob patterns.  Nested access is admitted by subtree containment
    under the canonicalized root; trailing ``/`` carries no special
    meaning here because canonicalization strips it.

    This field is **required** on :class:`ExecutorConfig` (no default
    factory): host-file access is a security-sensitive surface and
    every executor YAML must declare intent explicitly.  Empty lists
    are permitted and mean "no host-file paths allowed" — paired with
    ``host_files`` absent from ``adapters.enabled`` that is the
    deliberate "demo declines host-file access" declaration.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_read_paths: list[str] = Field(
        description=(
            "Real-path scope roots (with ~ allowed) that host-file reads may "
            "touch; subtree access is granted by containment under each "
            "canonicalized root, not by glob or trailing-slash syntax."
        ),
    )
    allowed_write_paths: list[str] = Field(
        description=(
            "Real-path scope roots (with ~ allowed) that host-file "
            "writes/deletes may touch; subtree access is granted by "
            "containment under each canonicalized root, not by glob or "
            "trailing-slash syntax."
        ),
    )

    @field_validator("allowed_read_paths", "allowed_write_paths", mode="after")
    @classmethod
    def _canonicalize(cls, paths: list[str]) -> list[str]:
        """Expand ``~`` + resolve symlinks on each path once at load time."""
        from resource_registry.floor import canonicalize_real_path

        return [canonicalize_real_path(p) for p in paths]


class SandboxConfig(BaseModel):
    """Configuration for RUN_COMMAND kernel-enforced sandboxing.

    When enabled, the executor wraps shell commands with a platform-specific
    sandbox (macOS Seatbelt via sandbox-exec, Linux bubblewrap in the future).
    All commands run under the highest-privilege template in
    ``allowed_templates`` — the admin-approved ceiling.

    If the sandbox engine is unavailable at runtime (wrong platform, missing
    binary), individual RUN_COMMAND requests are rejected -- the rest of the
    executor keeps running normally.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Master switch for RUN_COMMAND sandboxing.",
    )
    allowed_templates: list[str] = Field(
        default_factory=lambda: ["pure_compute", "file_read_only", "file_read_write"],
        description=(
            "Sandbox template ceiling. All commands run under the "
            "highest-privilege template in this list."
        ),
    )
    working_directory: str = Field(
        default="~/",
        description="Default cwd for sandboxed shell commands. Expanded at runtime.",
    )
    allowed_write_paths: list[str] = Field(
        default_factory=lambda: ["~/"],
        description="Paths where sandboxed commands can write. Expanded at runtime.",
    )
    executor_venv_path: str | None = Field(
        default=None,
        description=(
            "Absolute path to the executor's dedicated Python venv. When set "
            "(or auto-resolved from the owning user's HOME), sandboxed "
            "RUN_COMMAND gets VIRTUAL_ENV, a <venv>/bin-prefixed PATH, and "
            "PYTHONNOUSERSITE=1 so 'python', 'python3', 'pip', and 'uv pip' "
            "resolve to this venv. Package installs land here, never in the "
            "source-code venv or user-site. None + auto-resolution disabled "
            "means sandboxed Python falls back to system python3."
        ),
    )
    executor_venv_required: bool = Field(
        default=True,
        description=(
            "If True, the executor fails to start when the resolved venv is "
            "missing or lacks bin/python3. Recommended: True (fail loud at "
            "startup rather than silent wrong-Python at first RUN_COMMAND). "
            "Set False for minimal dev setups that want system python3."
        ),
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
    filesystem: FilesystemConfig = Field(default_factory=FilesystemConfig)
    host_files: HostFilesConfig = Field(
        description=(
            "Host-file allowlists (read + write).  Required: every YAML "
            "must declare intent explicitly — empty lists are allowed "
            "and mean 'no host-file paths', pair that with the adapter "
            "absent from adapters.enabled to fully opt out."
        ),
    )
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
