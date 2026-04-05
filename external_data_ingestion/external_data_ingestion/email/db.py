"""SQLite schema, migrations, and async connection factory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA_VERSION = 3

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    email          TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL DEFAULT '',
    provider       TEXT NOT NULL DEFAULT 'other',
    imap_host      TEXT NOT NULL,
    smtp_host      TEXT NOT NULL,
    imap_port      INTEGER NOT NULL DEFAULT 993,
    smtp_port      INTEGER NOT NULL DEFAULT 465,
    status         TEXT NOT NULL DEFAULT 'active',
    last_error     TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS emails (
    id             INTEGER PRIMARY KEY,
    uid            INTEGER NOT NULL,
    message_id     TEXT NOT NULL DEFAULT '',
    account_email  TEXT NOT NULL,
    mailbox        TEXT NOT NULL,
    subject        TEXT NOT NULL DEFAULT '',
    sender_raw     TEXT NOT NULL DEFAULT '',
    sender_name    TEXT NOT NULL DEFAULT '',
    sender_email   TEXT NOT NULL DEFAULT '',
    sender_domain  TEXT NOT NULL DEFAULT '',
    to_recipients  TEXT NOT NULL DEFAULT '[]',
    cc_recipients  TEXT NOT NULL DEFAULT '[]',
    date           TEXT NOT NULL DEFAULT '',
    body_plain     TEXT NOT NULL DEFAULT '',
    body_html      TEXT NOT NULL DEFAULT '',
    flags          TEXT NOT NULL DEFAULT '[]',
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    has_attachments INTEGER NOT NULL DEFAULT 0,
    in_reply_to    TEXT NOT NULL DEFAULT '',
    references_hdr TEXT NOT NULL DEFAULT '',
    headers_raw    TEXT NOT NULL DEFAULT '',
    content_level  INTEGER NOT NULL DEFAULT 0,
    synced_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (account_email, message_id)
);

CREATE INDEX IF NOT EXISTS idx_emails_account_mailbox
    ON emails (account_email, mailbox);
CREATE INDEX IF NOT EXISTS idx_emails_account_mailbox_uid
    ON emails (account_email, mailbox, uid);
CREATE INDEX IF NOT EXISTS idx_emails_date
    ON emails (date DESC);
CREATE INDEX IF NOT EXISTS idx_emails_sender
    ON emails (sender_email);
CREATE INDEX IF NOT EXISTS idx_emails_account_message_id
    ON emails (account_email, message_id);

CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject,
    sender_raw,
    body_plain,
    content=emails,
    content_rowid=id,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, sender_raw, body_plain)
    VALUES (new.id, new.subject, new.sender_raw, new.body_plain);
END;

CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, sender_raw, body_plain)
    VALUES ('delete', old.id, old.subject, old.sender_raw, old.body_plain);
END;

CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, sender_raw, body_plain)
    VALUES ('delete', old.id, old.subject, old.sender_raw, old.body_plain);
    INSERT INTO emails_fts(rowid, subject, sender_raw, body_plain)
    VALUES (new.id, new.subject, new.sender_raw, new.body_plain);
END;

CREATE TABLE IF NOT EXISTS attachments (
    id             INTEGER PRIMARY KEY,
    email_id       INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL DEFAULT '',
    content_type   TEXT NOT NULL DEFAULT '',
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    content_id     TEXT NOT NULL DEFAULT '',
    is_inline      INTEGER NOT NULL DEFAULT 0,
    storage_path   TEXT,
    content_blob   BLOB
);

CREATE TABLE IF NOT EXISTS folders (
    account_email  TEXT NOT NULL,
    name           TEXT NOT NULL,
    role           TEXT,
    delimiter      TEXT NOT NULL DEFAULT '/',
    flags          TEXT NOT NULL DEFAULT '[]',
    selectable     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (account_email, name)
);

CREATE TABLE IF NOT EXISTS sync_state (
    account_email  TEXT NOT NULL,
    mailbox        TEXT NOT NULL,
    uidvalidity    INTEGER NOT NULL DEFAULT 0,
    last_uid       INTEGER NOT NULL DEFAULT 0,
    message_count  INTEGER NOT NULL DEFAULT 0,
    last_sync_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_email, mailbox)
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type     TEXT NOT NULL,
    account_email  TEXT NOT NULL DEFAULT '',
    message_id     TEXT NOT NULL DEFAULT '',
    data           TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_events_id ON events (id);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


async def get_connection(db_path: Path | str) -> aiosqlite.Connection:
    """Open an aiosqlite connection with WAL mode and row factory."""
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_db(db_path: Path | str) -> aiosqlite.Connection:
    """Create tables if needed and return a ready connection."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    db = await get_connection(path)

    version = 0
    try:
        async with db.execute("SELECT version FROM schema_version LIMIT 1") as cur:
            row = await cur.fetchone()
            if row:
                version = row[0]
    except Exception:
        pass

    if version < SCHEMA_VERSION:
        # v1 -> v2: add content_level column; existing rows have full content
        if version >= 1:
            try:
                await db.execute(
                    "ALTER TABLE emails ADD COLUMN content_level INTEGER NOT NULL DEFAULT 0"
                )
                await db.execute("UPDATE emails SET content_level = 1")
                await db.commit()
            except Exception:
                pass  # column already exists (re-run safe)

        # v2 -> v3: add folders table (additive — executescript creates it)

        await db.executescript(SCHEMA_SQL)
        await db.execute("DELETE FROM schema_version")
        await db.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        await db.commit()

    return db


async def write_event(
    db: aiosqlite.Connection,
    event_type: str,
    account_email: str = "",
    message_id: str = "",
    data: dict[str, Any] | None = None,
) -> int:
    """Insert an event row and return its id."""
    async with db.execute(
        """INSERT INTO events (event_type, account_email, message_id, data)
           VALUES (?, ?, ?, ?)""",
        (event_type, account_email, message_id, json.dumps(data or {})),
    ) as cur:
        event_id = cur.lastrowid
    await db.commit()
    return event_id  # type: ignore[return-value]
