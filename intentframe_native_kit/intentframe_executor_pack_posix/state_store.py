"""
SQLite state store implementation.

Stores execution checkpoints (for crash recovery) and rollback entries
(for undoing completed actions). Uses SQLite with WAL mode.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading

from executor_sdk.models import RollbackEntry, RollbackStatus, _utc_now
from executor_sdk.services.state_store import StateStore
from intentframe_native_kit.intentframe_executor_pack_posix.paths import default_data_dir

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id    TEXT UNIQUE NOT NULL,
    status          TEXT NOT NULL,
    checkpoint      TEXT,
    attempts        INTEGER DEFAULT 1,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_execution_id ON execution_state(execution_id);

CREATE TABLE IF NOT EXISTS rollback_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id    TEXT NOT NULL,
    rollback_id     TEXT UNIQUE NOT NULL,
    adapter_id      TEXT NOT NULL,
    rollback_data   TEXT,
    expires_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'AVAILABLE',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rollback_id ON rollback_registry(rollback_id);
CREATE INDEX IF NOT EXISTS idx_rollback_status ON rollback_registry(status);
"""


class SQLiteStateStore(StateStore):
    """SQLite-based state store for checkpoints and rollback.

    Thread-safe via threading.Lock. SQL operations run in
    asyncio.to_thread() to not block the event loop.
    """

    def __init__(self, db_path: str = "", **_kwargs) -> None:
        if not db_path:
            default_dir = default_data_dir()
            default_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(default_dir / "executor.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("SQLite state store: %s", db_path)

    # ── Checkpoints ───────────────────────────────────────────────────────

    async def save_checkpoint(
        self, execution_id: str, status: str, checkpoint_data: dict
    ) -> None:
        await asyncio.to_thread(
            self._sync_save_checkpoint, execution_id, status, checkpoint_data
        )

    def _sync_save_checkpoint(
        self, execution_id: str, status: str, checkpoint_data: dict
    ) -> None:
        checkpoint_json = json.dumps(checkpoint_data)
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO execution_state (execution_id, status, checkpoint, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(execution_id) DO UPDATE SET
                   status=excluded.status, checkpoint=excluded.checkpoint,
                   attempts=attempts+1, updated_at=excluded.updated_at""",
                (execution_id, status, checkpoint_json, now),
            )
            self._conn.commit()

    async def get_checkpoint(self, execution_id: str) -> dict | None:
        return await asyncio.to_thread(self._sync_get_checkpoint, execution_id)

    def _sync_get_checkpoint(self, execution_id: str) -> dict | None:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT checkpoint FROM execution_state WHERE execution_id=?",
                (execution_id,),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None:
                return None
            return json.loads(row[0])

    async def delete_checkpoint(self, execution_id: str) -> None:
        await asyncio.to_thread(self._sync_delete_checkpoint, execution_id)

    def _sync_delete_checkpoint(self, execution_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM execution_state WHERE execution_id=?",
                (execution_id,),
            )
            self._conn.commit()

    # ── Rollback Registry ─────────────────────────────────────────────────

    async def save_rollback(self, entry: RollbackEntry) -> None:
        await asyncio.to_thread(self._sync_save_rollback, entry)

    def _sync_save_rollback(self, entry: RollbackEntry) -> None:
        rollback_json = json.dumps(entry.rollback_data)
        with self._lock:
            self._conn.execute(
                """INSERT INTO rollback_registry
                   (execution_id, rollback_id, adapter_id, rollback_data,
                    expires_at, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.execution_id,
                    entry.rollback_id,
                    entry.adapter_id,
                    rollback_json,
                    entry.expires_at,
                    entry.status.value,
                    entry.created_at,
                ),
            )
            self._conn.commit()

    async def get_rollback(self, rollback_id: str) -> RollbackEntry | None:
        return await asyncio.to_thread(self._sync_get_rollback, rollback_id)

    def _sync_get_rollback(self, rollback_id: str) -> RollbackEntry | None:
        with self._lock:
            cursor = self._conn.execute(
                """SELECT execution_id, rollback_id, adapter_id, rollback_data,
                          expires_at, status, created_at
                   FROM rollback_registry
                   WHERE rollback_id=? AND status='AVAILABLE'""",
                (rollback_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            return RollbackEntry(
                execution_id=row[0],
                rollback_id=row[1],
                adapter_id=row[2],
                rollback_data=json.loads(row[3]) if row[3] else {},
                expires_at=row[4],
                status=RollbackStatus(row[5]),
                created_at=row[6],
            )

    async def update_rollback_status(
        self, rollback_id: str, status: RollbackStatus
    ) -> None:
        await asyncio.to_thread(
            self._sync_update_rollback_status, rollback_id, status
        )

    def _sync_update_rollback_status(
        self, rollback_id: str, status: RollbackStatus
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE rollback_registry SET status=? WHERE rollback_id=?",
                (status.value, rollback_id),
            )
            self._conn.commit()

    async def expire_rollbacks(self) -> int:
        return await asyncio.to_thread(self._sync_expire_rollbacks)

    def _sync_expire_rollbacks(self) -> int:
        now = _utc_now()
        with self._lock:
            cursor = self._conn.execute(
                """UPDATE rollback_registry SET status='EXPIRED'
                   WHERE status='AVAILABLE' AND expires_at IS NOT NULL
                   AND expires_at < ?""",
                (now,),
            )
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
