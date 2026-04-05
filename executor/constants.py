"""
Constants and defaults for the IntentFrame Executor.

All magic numbers, default paths, and configuration defaults
live here. Platform-specific paths are resolved at runtime
based on the host OS; these are the fallback defaults.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# Timeouts (seconds)
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_ADAPTER_TIMEOUT: float = 30.0
"""Maximum time an adapter has to complete a single execute() call."""

DEFAULT_AUTH_TIMEOUT: float = 5.0
"""Maximum time for authorization verification."""

DEFAULT_SHUTDOWN_TIMEOUT: float = 10.0
"""Maximum time to wait for graceful shutdown."""

# ═══════════════════════════════════════════════════════════════════════════════
# Worker Pool
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_MAX_WORKERS: int = 4
"""Default number of concurrent capability workers."""

# ═══════════════════════════════════════════════════════════════════════════════
# Audit & Security
# ═══════════════════════════════════════════════════════════════════════════════

HASH_ALGORITHM: str = "sha256"
"""Hash algorithm used for audit chain and param hashing."""

GENESIS_HASH: str = "0" * 64
"""Initial hash for the audit chain (before any entries)."""

AUDIT_TABLE: str = "audit_log"
ROLLBACK_TABLE: str = "rollback_registry"
STATE_TABLE: str = "execution_state"
SECURITY_TABLE: str = "security_events"

# ═══════════════════════════════════════════════════════════════════════════════
# Credential Scrubbing (re-exported from intentframe_credentials)
# ═══════════════════════════════════════════════════════════════════════════════

from intentframe_credentials.redaction import REDACTED_VALUE, SENSITIVE_KEYS

# ═══════════════════════════════════════════════════════════════════════════════
# Config Defaults
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG_FILENAME: str = "executor.yaml"
DEFAULT_DATABASE_FILENAME: str = "executor.db"
DEFAULT_LOG_FILENAME: str = "executor.log"

# ═══════════════════════════════════════════════════════════════════════════════
# Transport
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_UNIX_SOCKET_PATH: str = "/tmp/intentframe/executor.sock"
DEFAULT_GRPC_PORT: int = 50051
DEFAULT_REST_PORT: int = 8080
