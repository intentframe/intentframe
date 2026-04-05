"""SQLite store for gateway-owned data.

Provides persistent storage for:
- App preferences (key-value config)
- Future: audit log persistence, search indexes
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class AppStore:
    """Async SQLite store for gateway data."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AppStore opened: %s", self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("AppStore closed: %s", self._db_path)

    # --- Config (key-value preferences) ---

    async def config_get_all(self) -> dict[str, Any]:
        assert self._db
        cursor = await self._db.execute("SELECT key, value FROM app_config")
        rows = await cursor.fetchall()
        return {k: json.loads(v) for k, v in rows}

    async def config_get(self, key: str) -> Any | None:
        assert self._db
        cursor = await self._db.execute(
            "SELECT value FROM app_config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def config_set(self, key: str, value: Any) -> None:
        assert self._db
        await self._db.execute(
            """INSERT INTO app_config (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key)
               DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, json.dumps(value)),
        )
        await self._db.commit()

    async def config_delete(self, key: str) -> bool:
        assert self._db
        cursor = await self._db.execute(
            "DELETE FROM app_config WHERE key = ?", (key,)
        )
        await self._db.commit()
        return cursor.rowcount > 0
