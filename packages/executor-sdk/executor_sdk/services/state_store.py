"""
Abstract base class for execution state and rollback storage.

The state store persists execution checkpoints (for resumption after
crash) and rollback entries (for undoing completed actions). It works
alongside the audit logger but serves a different purpose:

    - Audit logger: immutable record of WHAT happened (for compliance)
    - State store: mutable record of WHERE we are (for crash recovery)
                   and WHAT we can undo (for rollback)

Implementations to create later:
    - sqlite_state_store.py  (default -- SQLite with WAL mode)
    - redis_state_store.py   (cloud -- Redis for distributed state)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from executor_sdk.exceptions import ConfigurationError
from executor_sdk.models import RollbackEntry, RollbackStatus

__all__ = ["StateStore", "register_state_store", "create_state_store"]

# ─── Plugin Registry ─────────────────────────────────────────────────────────

_STATE_REGISTRY: dict[str, type[StateStore]] = {}


def register_state_store(
    backend: str, store_class: type[StateStore]
) -> None:
    """Register a state store implementation for config-driven instantiation."""
    _STATE_REGISTRY[backend] = store_class


def create_state_store(config: Any) -> StateStore:
    """Instantiate the configured state store from the registry."""
    store_class = _STATE_REGISTRY.get(config.state_backend)
    if store_class is None:
        registered = ", ".join(sorted(_STATE_REGISTRY)) or "(none)"
        raise ConfigurationError(
            f"Unknown state backend: '{config.state_backend}'. "
            f"Registered backends: {registered}",
        )
    return store_class(db_path=config.database_path or "")


class StateStore(ABC):
    """Abstract base for execution state persistence.

    Contract:
        - Checkpoint data is JSON-serializable dicts.
        - Rollback entries are stored and queryable by execution_id.
        - All methods are async for I/O flexibility.
        - Implementations MUST be safe for concurrent access.
        - Credentials MUST NOT appear in checkpoint or rollback data.
    """

    # ── Execution Checkpoints (crash recovery) ────────────────────────────

    @abstractmethod
    async def save_checkpoint(
        self,
        execution_id: str,
        status: str,
        checkpoint_data: dict,
    ) -> None:
        """Save or update an execution checkpoint.

        Called by the gateway at key points during execution so that
        a crash can be recovered from the last checkpoint.

        Args:
            execution_id: Unique execution identifier.
            status: Current status string.
            checkpoint_data: JSON-serializable state for resumption.
        """
        ...

    @abstractmethod
    async def get_checkpoint(self, execution_id: str) -> dict | None:
        """Retrieve the latest checkpoint for an execution.

        Returns None if no checkpoint exists.
        """
        ...

    @abstractmethod
    async def delete_checkpoint(self, execution_id: str) -> None:
        """Delete checkpoint after successful completion.

        Called after an execution completes (success or permanent failure)
        to clean up transient state.
        """
        ...

    # ── Rollback Registry ─────────────────────────────────────────────────

    @abstractmethod
    async def save_rollback(self, entry: RollbackEntry) -> None:
        """Store a rollback capability for a completed execution.

        Called when an adapter reports rollback_available=True in its
        ExecutionResult. The rollback_data contains what the adapter
        needs to undo the action.
        """
        ...

    @abstractmethod
    async def get_rollback(self, rollback_id: str) -> RollbackEntry | None:
        """Retrieve a rollback entry by ID.

        Returns None if not found or if the entry has expired.
        """
        ...

    @abstractmethod
    async def update_rollback_status(
        self, rollback_id: str, status: RollbackStatus
    ) -> None:
        """Update the status of a rollback entry.

        Called after a rollback is executed, fails, or expires.
        """
        ...

    @abstractmethod
    async def expire_rollbacks(self) -> int:
        """Expire all rollback entries past their expiration time.

        Returns the number of entries expired. Should be called
        periodically by the gateway or a background task.
        """
        ...

    def close(self) -> None:
        """Release resources (DB connections, file handles, etc.)."""
