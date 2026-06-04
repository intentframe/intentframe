"""SQLite metadata store for credential records.

The keyring only stores secret values — it has no listing or query
capability.  This lightweight SQLite DB tracks the *metadata* for every
credential (namespace, key, delivery mode, timestamps, masked preview,
etc.) so the vault service can list, search, and serve dashboard data
without touching the actual secrets.

The database file lives at ``~/.intentframe/data/credentials.db`` by
default.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from intentframe_credentials.exceptions import MetadataStoreError
from intentframe_credentials.models import (
    CredentialRecord,
    DeliveryMode,
    MaskedSummary,
)

__all__ = ["MetadataStore"]

_DEFAULT_DB_DIR = Path.home() / ".intentframe" / "data"
_DEFAULT_DB_NAME = "credentials.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS credential_metadata (
    namespace    TEXT NOT NULL,
    key          TEXT NOT NULL,
    delivery_mode TEXT NOT NULL DEFAULT 'executor_only',
    allowed_consumers TEXT NOT NULL DEFAULT '[]',
    env_name     TEXT,
    validator_id TEXT,
    masked_preview TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    last_validated_at TEXT,
    last_used_at TEXT,
    PRIMARY KEY (namespace, key)
);
"""


class MetadataStore:
    """Async SQLite store for credential metadata."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_dir = Path(
                os.environ.get("INTENTFRAME_DATA_DIR", str(_DEFAULT_DB_DIR))
            )
            self._db_path = db_dir / _DEFAULT_DB_NAME
        else:
            self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        """Open the database and ensure the schema exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute(_CREATE_TABLE)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise MetadataStoreError("MetadataStore is not open")
        return self._conn

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def upsert(self, record: CredentialRecord) -> None:
        """Insert or replace metadata for a credential."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """
            INSERT INTO credential_metadata
                (namespace, key, delivery_mode, allowed_consumers,
                 env_name, validator_id, masked_preview,
                 created_at, updated_at, last_validated_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET
                delivery_mode = excluded.delivery_mode,
                allowed_consumers = excluded.allowed_consumers,
                env_name = excluded.env_name,
                validator_id = excluded.validator_id,
                masked_preview = excluded.masked_preview,
                updated_at = ?,
                last_validated_at = COALESCE(excluded.last_validated_at,
                                             credential_metadata.last_validated_at),
                last_used_at = COALESCE(excluded.last_used_at,
                                        credential_metadata.last_used_at)
            """,
            (
                record.namespace,
                record.key,
                record.delivery_mode.value,
                json.dumps(record.allowed_consumers),
                record.env_name,
                record.validator_id,
                record.masked_preview,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
                record.last_validated_at.isoformat() if record.last_validated_at else None,
                record.last_used_at.isoformat() if record.last_used_at else None,
                # for the ON CONFLICT updated_at:
                now,
            ),
        )
        await self._db.commit()

    async def delete(self, namespace: str, key: str) -> bool:
        """Remove metadata for a credential.  Returns True if a row was deleted."""
        cursor = await self._db.execute(
            "DELETE FROM credential_metadata WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get(self, namespace: str, key: str) -> CredentialRecord | None:
        """Fetch a single credential record."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_metadata WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        row = await cursor.fetchone()
        return self._row_to_record(row) if row else None

    async def list_keys(self, namespace: str) -> list[str]:
        """Return all key names stored under *namespace*."""
        cursor = await self._db.execute(
            "SELECT key FROM credential_metadata WHERE namespace = ?",
            (namespace,),
        )
        rows = await cursor.fetchall()
        return [r["key"] for r in rows]

    async def list_namespace_summaries(self, namespace: str) -> list[MaskedSummary]:
        """Return masked summaries for all credentials in a namespace."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_metadata WHERE namespace = ?",
            (namespace,),
        )
        return [self._row_to_summary(r) for r in await cursor.fetchall()]

    async def list_all_summaries(self) -> list[MaskedSummary]:
        """Return masked summaries for every credential in the store."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_metadata ORDER BY namespace, key"
        )
        return [self._row_to_summary(r) for r in await cursor.fetchall()]

    async def list_runtime_env(self) -> list[CredentialRecord]:
        """Return all credentials with ``delivery_mode = 'runtime_env'``."""
        cursor = await self._db.execute(
            "SELECT * FROM credential_metadata WHERE delivery_mode = ?",
            (DeliveryMode.RUNTIME_ENV.value,),
        )
        return [self._row_to_record(r) for r in await cursor.fetchall()]

    async def touch_last_used(self, namespace: str, key: str) -> None:
        """Update the ``last_used_at`` timestamp to now."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE credential_metadata SET last_used_at = ? WHERE namespace = ? AND key = ?",
            (now, namespace, key),
        )
        await self._db.commit()

    async def touch_last_validated(
        self, namespace: str, key: str, *, valid: bool,
    ) -> None:
        """Update the ``last_validated_at`` timestamp."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE credential_metadata SET last_validated_at = ? WHERE namespace = ? AND key = ?",
            (now, namespace, key),
        )
        await self._db.commit()

    async def count(self) -> int:
        """Total number of credential records."""
        cursor = await self._db.execute("SELECT COUNT(*) FROM credential_metadata")
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Row conversion ───────────────────────────────────────────────────

    @staticmethod
    def _row_to_record(row: aiosqlite.Row) -> CredentialRecord:
        return CredentialRecord(
            namespace=row["namespace"],
            key=row["key"],
            delivery_mode=DeliveryMode(row["delivery_mode"]),
            allowed_consumers=json.loads(row["allowed_consumers"]),
            env_name=row["env_name"],
            validator_id=row["validator_id"],
            masked_preview=row["masked_preview"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_validated_at=(
                datetime.fromisoformat(row["last_validated_at"])
                if row["last_validated_at"]
                else None
            ),
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"])
                if row["last_used_at"]
                else None
            ),
        )

    @staticmethod
    def _row_to_summary(row: aiosqlite.Row) -> MaskedSummary:
        return MaskedSummary(
            namespace=row["namespace"],
            key=row["key"],
            delivery_mode=DeliveryMode(row["delivery_mode"]),
            masked_preview=row["masked_preview"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_validated_at=(
                datetime.fromisoformat(row["last_validated_at"])
                if row["last_validated_at"]
                else None
            ),
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"])
                if row["last_used_at"]
                else None
            ),
        )
