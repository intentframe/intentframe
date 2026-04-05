"""EmailClient -- the single interface for all consumers.

Consumers just use email addresses.  Config, db, credentials are all
resolved internally from the daemon's workspace
(``~/.intentframe/email`` or ``INTENTFRAME_EMAIL_HOME``).
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiosqlite
import structlog
from imap_tools import AND

from . import actions
from .config import AccountConfig, ServiceConfig, load_config, load_config_async
from .db import init_db
from .imap_connection import get_provider
from .models import (
    Account,
    AccountNotFoundError,
    Attachment,
    DraftResult,
    Email,
    Event,
    Folder,
    SendResult,
)
from .threading_utils import get_thread as _get_thread_rows

log = structlog.get_logger()

EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EmailClient:
    """High-level async client for the email sync service.

    From async code (daemon, tests, anything with a running event loop)::

        client = await EmailClient.create()

    From sync code (separate processes, CLI scripts)::

        client = EmailClient()

    All methods accept ``account_email`` (a plain email address string)
    to identify which account to operate on.  Credentials and server
    details are resolved internally from the daemon's workspace config.
    """

    def __init__(self, config: ServiceConfig | None = None) -> None:
        self._config = config or load_config()
        self._db: aiosqlite.Connection | None = None
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._listener_task: asyncio.Task | None = None
        self._last_event_id: int = 0

    @classmethod
    async def create(cls) -> EmailClient:
        """Async factory — use when a running event loop exists."""
        config = await load_config_async()
        return cls(config)

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            self._db = await init_db(self._config.db_path)
        return self._db

    def _get_account(self, account_email: str) -> AccountConfig:
        for acc in self._config.accounts:
            if acc.email == account_email:
                return acc
        raise ValueError(f"Account {account_email!r} not found in config")

    def _require_account(self, account_email: str) -> None:
        """Raise ``AccountNotFoundError`` if *account_email* is not configured."""
        if not any(acc.email == account_email for acc in self._config.accounts):
            raise AccountNotFoundError(
                account_email,
                configured=[acc.email for acc in self._config.accounts],
            )

    # ── Read (direct SQLite) ─────────────────────────────────────

    async def list_accounts(self) -> list[Account]:
        db = await self._get_db()
        async with db.execute("SELECT * FROM accounts ORDER BY email") as cur:
            rows = await cur.fetchall()
        return [Account(**dict(r)) for r in rows]

    async def get_active_accounts(self) -> list[Account]:
        """Return accounts that are both configured and active in the DB.

        An account must appear in config.yaml (has credentials in vault)
        AND have ``status='active'`` in the SQLite accounts table (daemon
        has synced it successfully).
        """
        configured_emails = {acc.email for acc in self._config.accounts}
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM accounts WHERE status = 'active' ORDER BY email"
        ) as cur:
            rows = await cur.fetchall()
        return [Account(**dict(r)) for r in rows if r["email"] in configured_emails]

    async def list_folders(self, account_email: str) -> list[Folder]:
        self._require_account(account_email)
        db = await self._get_db()
        async with db.execute(
            """SELECT f.name, f.role, f.delimiter, f.flags,
                      COALESCE(cnt.n, 0) AS message_count
               FROM folders f
               LEFT JOIN (
                   SELECT mailbox, COUNT(*) AS n
                   FROM emails WHERE account_email = ?
                   GROUP BY mailbox
               ) cnt ON cnt.mailbox = f.name
               WHERE f.account_email = ?
               ORDER BY f.name""",
            (account_email, account_email),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Folder(
                name=r["name"],
                role=r["role"],
                delimiter=r["delimiter"] or "/",
                flags=json.loads(r["flags"]) if r["flags"] else [],
                message_count=r["message_count"],
            )
            for r in rows
        ]

    async def get_recent(
        self,
        account_email: str,
        mailbox: str = "INBOX",
        limit: int = 50,
        offset: int = 0,
        since: str | None = None,
    ) -> list[Email]:
        self._require_account(account_email)
        db = await self._get_db()
        params: list[Any] = [account_email, mailbox]
        where = "account_email = ? AND mailbox = ?"
        if since:
            where += " AND date >= ?"
            params.append(since)
        params.extend([limit, offset])

        async with db.execute(
            f"SELECT * FROM emails WHERE {where} ORDER BY date DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_email(r) for r in rows]

    async def get_email(
        self, message_id: str, *, headers_only: bool = False,
    ) -> Email | None:
        db = await self._get_db()
        async with db.execute(
            "SELECT * FROM emails WHERE message_id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        email = _row_to_email(row)
        if not headers_only and email.content_level == 0:
            try:
                await self._fetch_body_on_demand(email)
            except Exception:
                log.exception("lazy_body_fetch_error", message_id=message_id)
                return email
            async with db.execute(
                "SELECT * FROM emails WHERE message_id = ?", (message_id,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                email = _row_to_email(row)
        return email

    async def get_thread(self, message_id: str) -> list[Email]:
        db = await self._get_db()
        rows = await _get_thread_rows(db, message_id)
        return [_dict_to_email(r) for r in rows]

    async def search(
        self,
        query: str,
        account_email: str | None = None,
        mailbox: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Email]:
        from .query_parser import build_search_sql, parse_email_query

        if account_email is not None:
            self._require_account(account_email)

        parsed = parse_email_query(query)

        if mailbox and not parsed.mailbox:
            parsed.mailbox = mailbox
        if since and not parsed.date_after:
            parsed.date_after = since

        sql, params = build_search_sql(parsed, account_email, limit)

        db = await self._get_db()
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_email(r) for r in rows]

    async def download_attachment(
        self, message_id: str, filename: str
    ) -> bytes | None:
        db = await self._get_db()
        async with db.execute(
            """SELECT a.content_blob, a.storage_path
               FROM attachments a
               JOIN emails e ON e.id = a.email_id
               WHERE e.message_id = ? AND a.filename = ?""",
            (message_id, filename),
        ) as cur:
            row = await cur.fetchone()

        if row:
            if row["content_blob"]:
                return bytes(row["content_blob"])
            if row["storage_path"]:
                path = Path(row["storage_path"])
                if path.exists():
                    return path.read_bytes()

        email = await self.get_email(message_id)
        if not email:
            return None
        return await self._fetch_attachment_on_demand(email, filename)

    async def list_attachments(self, message_id: str) -> list[Attachment]:
        """Return attachment metadata (no payload) for a given message."""
        db = await self._get_db()
        async with db.execute(
            """SELECT a.id, a.email_id, a.filename, a.content_type,
                      a.size_bytes, a.content_id, a.is_inline
               FROM attachments a
               JOIN emails e ON e.id = a.email_id
               WHERE e.message_id = ?
               ORDER BY a.id""",
            (message_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Attachment(
                id=r["id"],
                email_id=r["email_id"],
                filename=r["filename"],
                content_type=r["content_type"],
                size_bytes=r["size_bytes"],
                content_id=r["content_id"],
                is_inline=bool(r["is_inline"]),
            )
            for r in rows
        ]

    async def get_unread_count(
        self, account_email: str, mailbox: str = "INBOX"
    ) -> int:
        self._require_account(account_email)
        db = await self._get_db()
        async with db.execute(
            """SELECT COUNT(*) FROM emails
               WHERE account_email = ? AND mailbox = ?
               AND flags NOT LIKE '%Seen%'""",
            (account_email, mailbox),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_message_count(
        self, account_email: str, mailbox: str,
    ) -> int:
        """Return total number of messages for an account in a mailbox."""
        self._require_account(account_email)
        db = await self._get_db()
        async with db.execute(
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ?",
            (account_email, mailbox),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    # ── Write (direct IMAP/SMTP) ─────────────────────────────────

    async def send(
        self,
        account_email: str,
        to: list[str],
        subject: str,
        body: str,
        *,
        cc: list[str] | None = None,
        html: str = "",
    ) -> SendResult:
        try:
            account = self._get_account(account_email)
        except ValueError:
            return SendResult(success=False, error=f"Account {account_email!r} not configured")
        db = await self._get_db()
        return await actions.send_email(
            account, db, to, subject, body, cc=cc, html=html
        )

    async def create_draft(
        self,
        account_email: str,
        to: list[str],
        subject: str,
        body: str,
        *,
        cc: list[str] | None = None,
        html: str = "",
    ) -> DraftResult:
        try:
            account = self._get_account(account_email)
        except ValueError:
            return DraftResult(success=False, error=f"Account {account_email!r} not configured")
        db = await self._get_db()
        return await actions.create_draft(
            account, db, to, subject, body, cc=cc, html=html
        )

    async def reply(
        self,
        message_id: str,
        body: str,
        *,
        html: str = "",
        reply_all: bool = False,
        as_draft: bool = False,
    ) -> SendResult | DraftResult:
        email_obj = await self.get_email(message_id)
        if not email_obj:
            return SendResult(success=False, error="Email not found")
        account = self._get_account(email_obj.account_email)
        db = await self._get_db()
        return await actions.reply(
            account, db, message_id, body, html=html, reply_all=reply_all, as_draft=as_draft
        )

    async def forward(
        self,
        message_id: str,
        to: list[str],
        body: str = "",
        *,
        html: str = "",
        as_draft: bool = False,
    ) -> SendResult | DraftResult:
        email_obj = await self.get_email(message_id)
        if not email_obj:
            return SendResult(success=False, error="Email not found")
        account = self._get_account(email_obj.account_email)
        db = await self._get_db()
        return await actions.forward(
            account, db, message_id, to, body, html=html, as_draft=as_draft
        )

    async def mark_read(self, message_id: str, *, read: bool = True) -> None:
        email_obj = await self.get_email(message_id)
        if not email_obj:
            return
        account = self._get_account(email_obj.account_email)
        db = await self._get_db()
        await actions.mark_read(account, db, message_id, read=read)

    async def move(self, message_id: str, to_folder: str) -> None:
        email_obj = await self.get_email(message_id)
        if not email_obj:
            return
        account = self._get_account(email_obj.account_email)
        db = await self._get_db()
        await actions.move_email(account, db, message_id, to_folder)

    async def delete(self, message_id: str) -> None:
        email_obj = await self.get_email(message_id)
        if not email_obj:
            return
        account = self._get_account(email_obj.account_email)
        db = await self._get_db()
        await actions.delete_email(account, db, message_id)

    # ── Observer ─────────────────────────────────────────────────

    def on(self, event_type: str) -> Callable:
        """Decorator to register an event handler.

        Usage::

            @client.on("new_email")
            async def handle_new(event: Event):
                ...

            @client.on("*")
            async def catch_all(event: Event):
                ...
        """

        def decorator(fn: EventHandler) -> EventHandler:
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    async def start_listening(self, poll_interval: float = 1.0) -> None:
        """Start polling the events table in a background task."""
        if self._listener_task and not self._listener_task.done():
            return

        db = await self._get_db()
        async with db.execute("SELECT MAX(id) FROM events") as cur:
            row = await cur.fetchone()
            self._last_event_id = (row[0] or 0) if row else 0

        self._listener_task = asyncio.create_task(
            self._poll_events(poll_interval), name="email-event-listener"
        )

    async def stop_listening(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

    async def close(self) -> None:
        await self.stop_listening()
        if self._db:
            await self._db.close()
            self._db = None

    # ── On-demand fetch helpers ───────────────────────────────────

    async def _fetch_body_on_demand(self, email: Email) -> None:
        """Connect to IMAP and fetch the full body for a headers-only message."""
        account = self._get_account(email.account_email)
        db = await self._get_db()

        provider = get_provider(account)
        async with provider.connection() as mb:
            def _fetch():
                mb.folder.set(email.mailbox, readonly=True)
                msgs = list(mb.fetch(AND(uid=str(email.uid)), mark_seen=False))
                return msgs[0] if msgs else None
            msg = await asyncio.to_thread(_fetch)
        if not msg:
            log.warning("on_demand_body_fetch_failed", message_id=email.message_id)
            return

        async with db.execute(
            """UPDATE emails
               SET body_plain = ?, body_html = ?, has_attachments = ?,
                   size_bytes = ?, content_level = 1
               WHERE id = ? AND content_level = 0""",
            (
                msg.text, msg.html, 1 if msg.attachments else 0,
                msg.size_rfc822 or msg.size, email.id,
            ),
        ) as cur:
            changed = cur.rowcount

        if changed and msg.attachments:
            for att in msg.attachments:
                await db.execute(
                    """INSERT INTO attachments
                       (email_id, filename, content_type, size_bytes, content_id, is_inline)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        email.id,
                        att.filename,
                        att.content_type,
                        len(att.payload),
                        att.content_id,
                        1 if att.content_disposition == "inline" else 0,
                    ),
                )
        await db.commit()
        log.info("on_demand_body_fetched", message_id=email.message_id)

    async def _fetch_attachment_on_demand(
        self, email: Email, filename: str,
    ) -> bytes | None:
        """Connect to IMAP and fetch a specific attachment payload."""
        account = self._get_account(email.account_email)
        db = await self._get_db()

        provider = get_provider(account)
        async with provider.connection() as mb:
            def _fetch():
                mb.folder.set(email.mailbox, readonly=True)
                msgs = list(mb.fetch(AND(uid=str(email.uid)), mark_seen=False))
                if not msgs:
                    return None
                for att in msgs[0].attachments:
                    if att.filename == filename:
                        return att.payload
                return None
            payload = await asyncio.to_thread(_fetch)
        if payload is None:
            return None

        from .sync import ATTACHMENT_DISK_THRESHOLD

        size = len(payload)
        storage_path = None
        content_blob = None

        if size >= ATTACHMENT_DISK_THRESHOLD:
            att_dir = self._config.attachments_dir
            att_dir.mkdir(parents=True, exist_ok=True)
            safe_name = filename.replace("/", "_").replace("\\", "_") or "attachment.bin"
            dest = att_dir / f"{email.id}_{safe_name}"
            dest.write_bytes(payload)
            storage_path = str(dest)
        else:
            content_blob = payload

        await db.execute(
            """UPDATE attachments SET storage_path = ?, content_blob = ?
               WHERE email_id = ? AND filename = ?""",
            (storage_path, content_blob, email.id, filename),
        )
        await db.commit()
        log.info("on_demand_attachment_fetched", message_id=email.message_id, filename=filename)
        return payload

    async def _poll_events(self, interval: float) -> None:
        while True:
            try:
                db = await self._get_db()
                async with db.execute(
                    "SELECT * FROM events WHERE id > ? ORDER BY id",
                    (self._last_event_id,),
                ) as cur:
                    rows = await cur.fetchall()

                for row in rows:
                    event = Event(
                        id=row["id"],
                        event_type=row["event_type"],
                        account_email=row["account_email"],
                        message_id=row["message_id"],
                        data=json.loads(row["data"] or "{}"),
                        created_at=row["created_at"],
                    )
                    self._last_event_id = event.id
                    await self._dispatch(event)

            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event_poll_error")

            await asyncio.sleep(interval)

    async def _dispatch(self, event: Event) -> None:
        handlers = self._handlers.get(event.event_type, []) + self._handlers.get(
            "*", []
        )
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                log.exception(
                    "event_handler_error",
                    event_type=event.event_type,
                    handler=handler.__name__,
                )


def _row_to_email(row: aiosqlite.Row) -> Email:
    d = dict(row)
    d["to_recipients"] = json.loads(d.get("to_recipients") or "[]")
    d["cc_recipients"] = json.loads(d.get("cc_recipients") or "[]")
    d["flags"] = json.loads(d.get("flags") or "[]")
    d["has_attachments"] = bool(d.get("has_attachments"))
    return Email(**d)


def _dict_to_email(d: dict) -> Email:
    d = dict(d)
    if isinstance(d.get("to_recipients"), str):
        d["to_recipients"] = json.loads(d["to_recipients"])
    if isinstance(d.get("cc_recipients"), str):
        d["cc_recipients"] = json.loads(d["cc_recipients"])
    if isinstance(d.get("flags"), str):
        d["flags"] = json.loads(d["flags"])
    d["has_attachments"] = bool(d.get("has_attachments"))
    return Email(**d)
