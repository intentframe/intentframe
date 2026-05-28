"""
SQLite audit logger implementation -- fully append-only.

Every audit event is an INSERT. No row is ever UPDATEd.
Each execution produces two rows (STARTED + COMPLETED/FAILED),
both linked into the same tamper-evident hash chain.

Uses SQLite with WAL mode for concurrent read/write access.
All SQL operations run in a thread pool to avoid blocking the
asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from pathlib import Path

from executor_sdk.models import AuditEntry, ExecutionStatus, SecurityEvent
from executor_sdk.services.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

# Append-only schema: no UNIQUE on execution_id (two rows per execution).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id    TEXT NOT NULL,
    intent_frame_id TEXT,
    action_type     TEXT NOT NULL,
    adapter_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    params_hash     TEXT,
    result_summary  TEXT,
    error           TEXT,
    duration_ms     INTEGER,
    timestamp       TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    entry_hash      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_execution_id ON audit_log(execution_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);

CREATE TABLE IF NOT EXISTS security_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    source_info TEXT,
    details     TEXT,
    timestamp   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_security_timestamp ON security_events(timestamp);
"""


class SQLiteAuditLogger(AuditLogger):
    """SQLite-based audit logger -- fully append-only with hash chain.

    Thread-safe: uses a threading.Lock around all database operations
    and runs SQL in asyncio.to_thread() to not block the event loop.

    Every call to log_event() INSERTs a new row. No rows are ever
    modified. The hash chain covers every field in every row.
    """

    def __init__(self, db_path: str = "", **_kwargs) -> None:
        if not db_path:
            default_dir = Path.home() / "Library" / "Application Support" / "IntentFrame"
            default_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(default_dir / "executor.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("SQLite audit logger (append-only): %s", db_path)

    # ── Core: append-only event logging ───────────────────────────────────

    async def log_event(self, entry: AuditEntry) -> None:
        """INSERT an immutable audit event. Never UPDATEs."""
        await asyncio.to_thread(self._sync_log_event, entry)

    def _sync_log_event(self, entry: AuditEntry) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO audit_log
                   (execution_id, intent_frame_id, action_type, adapter_id,
                    status, params_hash, result_summary, error, duration_ms,
                    timestamp, prev_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.execution_id,
                    entry.intent_frame_id,
                    entry.action_type,
                    entry.adapter_id,
                    entry.status.value,
                    entry.params_hash,
                    entry.result_summary,
                    entry.error,
                    entry.duration_ms,
                    entry.timestamp,
                    entry.prev_hash,
                    entry.entry_hash,
                ),
            )
            self._conn.commit()

    # ── Security events ───────────────────────────────────────────────────

    async def log_security_event(self, event: SecurityEvent) -> None:
        await asyncio.to_thread(self._sync_log_security_event, event)

    def _sync_log_security_event(self, event: SecurityEvent) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO security_events
                   (event_type, source_info, details, timestamp)
                   VALUES (?, ?, ?, ?)""",
                (
                    event.event_type.value,
                    event.source_info,
                    event.details,
                    event.timestamp,
                ),
            )
            self._conn.commit()

    # ── Query ─────────────────────────────────────────────────────────────

    async def get_entries(self, execution_id: str) -> list[AuditEntry]:
        """Return all events for an execution, ordered chronologically."""
        return await asyncio.to_thread(self._sync_get_entries, execution_id)

    def _sync_get_entries(self, execution_id: str) -> list[AuditEntry]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM audit_log WHERE execution_id=? ORDER BY id ASC",
                (execution_id,),
            )
            columns = [desc[0] for desc in cursor.description]
            entries = []
            for row in cursor.fetchall():
                data = dict(zip(columns, row))
                data["status"] = ExecutionStatus(data["status"])
                data.pop("id", None)
                entries.append(AuditEntry(**data))
            return entries

    # ── Chain verification ────────────────────────────────────────────────

    async def verify_chain_integrity(self) -> bool:
        return await asyncio.to_thread(self._sync_verify_chain)

    def _sync_verify_chain(self) -> bool:
        """Verify the entire hash chain.

        Append-only means every field is hash-protected. We hash the
        full row (minus id, entry_hash, prev_hash) and compare to the
        stored entry_hash. We also verify chain linkage (each row's
        prev_hash matches the previous row's entry_hash).
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM audit_log ORDER BY id ASC"
            )
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not rows:
            return True

        from executor_sdk.services.hash_chain import HashChain

        # Only exclude the hash chain fields themselves and the auto-increment id.
        # Every other field is covered by the hash.
        _EXCLUDE = {"id", "entry_hash", "prev_hash"}

        for i, row in enumerate(rows):
            entry_data = {
                k: v for k, v in row.items()
                if k not in _EXCLUDE
            }
            computed = HashChain._compute_hash(entry_data, row["prev_hash"])
            if computed != row["entry_hash"]:
                return False
            if i > 0 and row["prev_hash"] != rows[i - 1]["entry_hash"]:
                return False

        return True

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
