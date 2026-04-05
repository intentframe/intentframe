"""Initial sync, incremental sync, and IMAP IDLE listener.

All IMAP connections are obtained through ``ConnectionProvider`` from
``imap_connection``.  No ``MailBox`` objects are created directly here.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import imaplib

import aiosqlite
import structlog
from imap_tools import AND, MailBox, MailMessage

from .config import AccountConfig
from .db import write_event
from .imap_connection import get_or_discover_folders, get_provider

log = structlog.get_logger()

ATTACHMENT_DISK_THRESHOLD = 1_000_000  # 1 MB


def _extract_email_row(
    msg: MailMessage,
    account_email: str,
    mailbox_name: str,
    *,
    headers_only: bool = False,
) -> dict[str, Any]:
    """Convert an imap-tools MailMessage to a dict suitable for DB insert."""
    from_values = msg.from_values
    sender_email = from_values.email if from_values else ""
    sender_name = from_values.name if from_values else ""
    sender_domain = sender_email.rsplit("@", 1)[-1] if "@" in sender_email else ""

    to_list = [{"name": a.name, "email": a.email} for a in msg.to_values]
    cc_list = [{"name": a.name, "email": a.email} for a in msg.cc_values]

    message_id_hdr = msg.headers.get("message-id", ("",))
    message_id = message_id_hdr[0] if message_id_hdr else ""

    in_reply_to_hdr = msg.headers.get("in-reply-to", ("",))
    in_reply_to = in_reply_to_hdr[0] if in_reply_to_hdr else ""

    references_hdr = msg.headers.get("references", ("",))
    references = references_hdr[0] if references_hdr else ""

    date_str = msg.date.isoformat() if msg.date.year > 1900 else ""

    headers_raw = ""
    if msg.obj:
        headers_raw = msg.obj.as_string().split("\n\n", 1)[0]

    return {
        "uid": int(msg.uid) if msg.uid else 0,
        "message_id": message_id,
        "account_email": account_email,
        "mailbox": mailbox_name,
        "subject": msg.subject,
        "sender_raw": str(msg.from_values.full if msg.from_values else ""),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "sender_domain": sender_domain,
        "to_recipients": json.dumps(to_list),
        "cc_recipients": json.dumps(cc_list),
        "date": date_str,
        "body_plain": "" if headers_only else msg.text,
        "body_html": "" if headers_only else msg.html,
        "flags": json.dumps(list(msg.flags)),
        "size_bytes": msg.size_rfc822 or msg.size,
        "has_attachments": 0 if headers_only else (1 if msg.attachments else 0),
        "in_reply_to": in_reply_to,
        "references_hdr": references,
        "headers_raw": headers_raw,
        "content_level": 0 if headers_only else 1,
    }


async def _store_attachments(
    db: aiosqlite.Connection,
    email_row_id: int,
    msg: MailMessage,
    attachments_dir: Any,
    *,
    metadata_only: bool = False,
) -> None:
    """Persist attachment metadata (and optionally content) to DB / disk.

    When *metadata_only* is ``True`` only the metadata row is inserted;
    no payload bytes are stored.  The actual content will be fetched
    on-demand by ``EmailClient.download_attachment()``.
    """
    from pathlib import Path

    att_dir = Path(attachments_dir)

    for att in msg.attachments:
        payload = att.payload
        size = len(payload)
        storage_path = None
        content_blob = None

        if not metadata_only:
            if size >= ATTACHMENT_DISK_THRESHOLD:
                att_dir.mkdir(parents=True, exist_ok=True)
                safe_name = (
                    att.filename.replace("/", "_").replace("\\", "_") or "attachment.bin"
                )
                dest = att_dir / f"{email_row_id}_{safe_name}"
                dest.write_bytes(payload)
                storage_path = str(dest)
            else:
                content_blob = payload

        await db.execute(
            """INSERT INTO attachments
               (email_id, filename, content_type, size_bytes, content_id, is_inline, storage_path, content_blob)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email_row_id,
                att.filename,
                att.content_type,
                size,
                att.content_id,
                1 if att.content_disposition == "inline" else 0,
                storage_path,
                content_blob,
            ),
        )


async def _insert_email(
    db: aiosqlite.Connection,
    row: dict[str, Any],
    msg: MailMessage,
    attachments_dir: Any,
    *,
    metadata_only: bool = False,
    skip_attachments: bool = False,
) -> int | None:
    """Insert a single email row. Returns row id or None if duplicate.

    *metadata_only* is forwarded to ``_store_attachments`` so that
    only metadata rows are created (no payload bytes).
    *skip_attachments* skips attachment storage entirely (used for
    headers-only sync where no attachment info is available).
    """
    cols = list(row.keys())
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)

    try:
        async with db.execute(
            f"INSERT OR IGNORE INTO emails ({col_names}) VALUES ({placeholders})",
            tuple(row.values()),
        ) as cur:
            if cur.lastrowid and cur.rowcount:
                email_id = cur.lastrowid
                if msg.attachments and not skip_attachments:
                    await _store_attachments(
                        db, email_id, msg, attachments_dir,
                        metadata_only=metadata_only,
                    )
                return email_id
    except Exception:
        log.exception("insert_email_failed", message_id=row.get("message_id"))
    return None


async def sync_folder(
    account: AccountConfig,
    mailbox_name: str,
    db: aiosqlite.Connection,
    attachments_dir: Any,
    *,
    full: bool = False,
    headers_only: bool = False,
    since_days: int | None = None,
    mb: MailBox,
) -> int:
    """Sync a single IMAP folder into the local DB.

    When *headers_only* is ``True``, only message headers are fetched
    (``BODY.PEEK[HEADER]``), producing ``content_level=0`` rows with
    empty bodies and no attachment info.

    When *since_days* is set and no prior sync state exists, the IMAP
    ``SINCE`` filter is used so the server only returns messages within
    the window.  This is much faster than fetching ALL when only recent
    content is needed.

    *mb* is the IMAP connection to use (caller retains ownership — the
    connection is **not** closed here).

    Returns the number of new messages inserted.
    """
    log.info(
        "sync_folder_start",
        account=account.email,
        mailbox=mailbox_name,
        full=full,
        headers_only=headers_only,
    )

    last_uid = 0
    uidvalidity = 0

    if not full:
        async with db.execute(
            "SELECT uidvalidity, last_uid FROM sync_state WHERE account_email = ? AND mailbox = ?",
            (account.email, mailbox_name),
        ) as cur:
            row = await cur.fetchone()
            if row:
                uidvalidity = row[0]
                last_uid = row[1]

    _ho = headers_only

    def _fetch_messages_with(conn: MailBox) -> tuple[list[MailMessage], int]:
        conn.folder.set(mailbox_name, readonly=True)

        status = conn.folder.status(mailbox_name)
        server_uidvalidity = status.get("UIDVALIDITY", 0)

        if uidvalidity and server_uidvalidity != uidvalidity:
            log.warning(
                "uidvalidity_changed",
                account=account.email,
                mailbox=mailbox_name,
                old=uidvalidity,
                new=server_uidvalidity,
            )
            criteria = "ALL"
        elif last_uid:
            criteria = AND(uid=f"{last_uid + 1}:*")
        elif since_days is not None:
            cutoff = date.today() - timedelta(days=since_days)
            criteria = AND(date_gte=cutoff)
        else:
            criteria = "ALL"

        messages = list(
            conn.fetch(criteria, mark_seen=False, bulk=50, headers_only=_ho)
        )
        return messages, server_uidvalidity

    messages, server_uidvalidity = await asyncio.to_thread(
        _fetch_messages_with, mb,
    )

    inserted = 0
    max_uid = last_uid
    for msg in messages:
        msg_uid = int(msg.uid) if msg.uid else 0
        if msg_uid and msg_uid <= last_uid and not full:
            continue

        row = _extract_email_row(
            msg, account.email, mailbox_name, headers_only=headers_only,
        )
        email_id = await _insert_email(
            db, row, msg, attachments_dir, metadata_only=True,
            skip_attachments=headers_only,
        )
        if email_id:
            inserted += 1
            await write_event(
                db,
                "new_email",
                account_email=account.email,
                message_id=row["message_id"],
                data={"uid": msg_uid, "mailbox": mailbox_name, "subject": msg.subject},
            )
        if msg_uid > max_uid:
            max_uid = msg_uid

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.execute(
        """INSERT INTO sync_state (account_email, mailbox, uidvalidity, last_uid, message_count, last_sync_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (account_email, mailbox) DO UPDATE SET
               uidvalidity = excluded.uidvalidity,
               last_uid = excluded.last_uid,
               message_count = excluded.message_count,
               last_sync_at = excluded.last_sync_at""",
        (account.email, mailbox_name, server_uidvalidity, max_uid, len(messages), now),
    )
    await db.commit()

    log.info(
        "sync_folder_done",
        account=account.email,
        mailbox=mailbox_name,
        fetched=len(messages),
        inserted=inserted,
        headers_only=headers_only,
    )
    return inserted


async def upgrade_folder_bodies(
    account: AccountConfig,
    mailbox_name: str,
    db: aiosqlite.Connection,
    attachments_dir: Any,
    since_days: int = 90,
    *,
    mb: MailBox,
) -> int:
    """Fetch full bodies for headers-only messages within *since_days*.

    Selects UIDs from the DB that still have ``content_level=0`` and a
    date within the window, re-fetches them from IMAP with full body,
    and updates the rows.  Attachment metadata (no payloads) is stored.

    *mb* is the IMAP connection to use (caller retains ownership).

    Returns the number of messages upgraded.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=since_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    async with db.execute(
        """SELECT uid FROM emails
           WHERE account_email = ? AND mailbox = ?
             AND content_level = 0 AND date >= ?""",
        (account.email, mailbox_name, cutoff),
    ) as cur:
        rows = await cur.fetchall()

    uids_to_upgrade = [r[0] for r in rows if r[0]]
    if not uids_to_upgrade:
        return 0

    log.info(
        "upgrade_bodies_start",
        account=account.email,
        mailbox=mailbox_name,
        count=len(uids_to_upgrade),
    )

    uid_set = ",".join(str(u) for u in uids_to_upgrade)

    def _fetch_bodies_with(conn: MailBox) -> list[MailMessage]:
        conn.folder.set(mailbox_name, readonly=True)
        return list(
            conn.fetch(AND(uid=uid_set), mark_seen=False, bulk=50)
        )

    messages = await asyncio.to_thread(_fetch_bodies_with, mb)

    upgraded = 0
    for msg in messages:
        msg_uid = int(msg.uid) if msg.uid else 0
        if not msg_uid:
            continue

        async with db.execute(
            """UPDATE emails
               SET body_plain = ?, body_html = ?, has_attachments = ?,
                   size_bytes = ?, content_level = 1
               WHERE account_email = ? AND mailbox = ? AND uid = ? AND content_level = 0""",
            (
                msg.text,
                msg.html,
                1 if msg.attachments else 0,
                msg.size_rfc822 or msg.size,
                account.email,
                mailbox_name,
                msg_uid,
            ),
        ) as cur:
            changed = cur.rowcount

        if not changed:
            continue

        if msg.attachments:
            async with db.execute(
                "SELECT id FROM emails WHERE account_email = ? AND mailbox = ? AND uid = ?",
                (account.email, mailbox_name, msg_uid),
            ) as cur:
                id_row = await cur.fetchone()
            if id_row:
                await _store_attachments(
                    db, id_row[0], msg, attachments_dir, metadata_only=True,
                )

        upgraded += 1

    await db.commit()

    log.info(
        "upgrade_bodies_done",
        account=account.email,
        mailbox=mailbox_name,
        upgraded=upgraded,
    )
    return upgraded


async def upgrade_all_folders_bodies(
    account: AccountConfig,
    db: aiosqlite.Connection,
    attachments_dir: Any,
    since_days: int = 90,
    *,
    skip_roles: set[str] | None = None,
) -> int:
    """Upgrade bodies for all folders of an account.

    After headers have been fetched, fetch bodies for the recent window.
    *skip_roles* excludes folders whose RFC 6154 role is in the set.

    Opens a single IMAP connection via ``ConnectionProvider`` and
    reuses it across all folders.
    """
    provider = get_provider(account)
    async with provider.connection() as conn:
        folders = await get_or_discover_folders(conn, account.email)

        total = 0
        selectable = [f for f in folders if f.get("selectable", True)]
        if skip_roles:
            selectable = [f for f in selectable if f.get("role") not in skip_roles]
        for i, folder_info in enumerate(selectable):
            name = folder_info["name"]
            log.info(
                "upgrade_progress",
                account=account.email,
                folder_num=i + 1,
                folder_total=len(selectable),
                folder=name,
            )
            try:
                count = await upgrade_folder_bodies(
                    account, name, db, attachments_dir,
                    since_days=since_days, mb=conn,
                )
                total += count
            except (imaplib.IMAP4.abort, ConnectionError, OSError):
                raise
            except Exception:
                log.exception("upgrade_folder_error", account=account.email, folder=name)

        return total


async def sync_all_folders(
    account: AccountConfig,
    db: aiosqlite.Connection,
    attachments_dir: Any,
    *,
    headers_only: bool = False,
    skip_roles: set[str] | None = None,
) -> int:
    """Discover all folders and sync each one. Returns total new messages.

    *skip_roles* excludes folders whose RFC 6154 role is in the set
    (e.g. ``{"all"}`` skips Gmail's All Mail).

    Opens a single IMAP connection via ``ConnectionProvider`` and
    reuses it across all folders.
    """
    provider = get_provider(account)
    async with provider.connection() as conn:
        folders = await get_or_discover_folders(conn, account.email)

        total = 0
        selectable = [f for f in folders if f.get("selectable", True)]
        if skip_roles:
            selectable = [f for f in selectable if f.get("role") not in skip_roles]
        for i, folder_info in enumerate(selectable):
            name = folder_info["name"]
            log.info(
                "sync_progress",
                account=account.email,
                folder_num=i + 1,
                folder_total=len(selectable),
                folder=name,
                headers_only=headers_only,
            )
            try:
                count = await sync_folder(
                    account, name, db, attachments_dir,
                    headers_only=headers_only, mb=conn,
                )
                total += count
            except (imaplib.IMAP4.abort, ConnectionError, OSError):
                raise
            except Exception:
                log.exception("sync_folder_error", account=account.email, folder=name)
                await write_event(
                    db,
                    "sync_error",
                    account_email=account.email,
                    data={"mailbox": name},
                )

        await write_event(
            db,
            "sync_complete",
            account_email=account.email,
            data={"folders": len(selectable), "new_messages": total},
        )
        return total


async def run_idle(
    account: AccountConfig,
    db: aiosqlite.Connection,
    attachments_dir: Any,
    *,
    stop_event: asyncio.Event | None = None,
    idle_connections: list[MailBox] | None = None,
) -> None:
    """IMAP IDLE loop on INBOX for real-time new-mail notifications.

    Maintains a persistent connection via ``ConnectionProvider``,
    re-entering IDLE after each wakeup.  On wakeup the *same*
    connection is reused for ``sync_folder`` — no second login.

    Stops when *stop_event* is set.

    Pass *idle_connections* (a shared list) so that the caller can
    force-close every live connection to unblock threads instantly
    at shutdown time.
    """
    log.info("idle_start", account=account.email)
    _stop = stop_event or asyncio.Event()
    _conns = idle_connections
    consecutive_errors = 0
    MAX_BACKOFF = 300

    # Each idle.wait() blocks for up to IDLE_WAIT seconds.  After
    # IDLE_CYCLE_AFTER total seconds on one connection we break out,
    # return the connection, and re-acquire (health-checked).  This
    # mirrors what Apple Mail / Thunderbird do (~28 min cycle) and
    # ensures that silently-dead connections are detected promptly.
    IDLE_WAIT = 5 * 60          # 5 min per IDLE wait
    IDLE_CYCLE_AFTER = 25 * 60  # reconnect after 25 min

    provider = get_provider(account)

    while not _stop.is_set():
        try:
            async with provider.connection() as mb:
                if _conns is not None:
                    _conns.append(mb)
                try:
                    await asyncio.to_thread(mb.folder.set, "INBOX")
                    if consecutive_errors > 0:
                        log.info("idle_reconnected", account=account.email)

                    conn_start = asyncio.get_event_loop().time()

                    while not _stop.is_set():
                        responses = await asyncio.to_thread(
                            mb.idle.wait, timeout=IDLE_WAIT,
                        )
                        if _stop.is_set():
                            break
                        consecutive_errors = 0

                        if responses:
                            log.debug("idle_wakeup", account=account.email, responses=len(responses))
                            await sync_folder(account, "INBOX", db, attachments_dir, mb=mb)

                        elapsed = asyncio.get_event_loop().time() - conn_start
                        if elapsed >= IDLE_CYCLE_AFTER:
                            log.info(
                                "idle_cycle",
                                account=account.email,
                                held_seconds=int(elapsed),
                            )
                            break
                finally:
                    if _conns is not None and mb in _conns:
                        _conns.remove(mb)

        except Exception:
            if _stop.is_set():
                break
            consecutive_errors += 1
            backoff = min(30 * (2 ** (consecutive_errors - 1)), MAX_BACKOFF)
            log.exception(
                "idle_error",
                account=account.email,
                consecutive_errors=consecutive_errors,
                backoff_seconds=backoff,
            )
            try:
                await asyncio.wait_for(_stop.wait(), timeout=backoff)
            except TimeoutError:
                pass

    log.info("idle_stopped", account=account.email)


# ── Data integrity verification ──────────────────────────────────


async def verify_integrity(
    account: AccountConfig,
    db: aiosqlite.Connection,
    *,
    skip_roles: set[str] | None = None,
) -> dict:
    """Compare the local DB against the IMAP server for data integrity.

    For every selectable folder (excluding those in *skip_roles*), fetches
    the full UID list from the server (lightweight — no message data) and
    checks that each server UID has a corresponding local row.

    Gmail exposes the same message in multiple IMAP folders (labels), but
    the local DB stores each message once (under whichever folder was synced
    first).  To avoid false positives the check fetches Message-ID headers
    for candidate "missing" UIDs and verifies them against all local
    message_ids for the account.  UIDs whose message_id already exists
    locally (under a different mailbox) are reported as *cross_folder*
    rather than *missing*.

    Uses a single IMAP connection for discovery, UID enumeration, and
    candidate Message-ID fetching.

    Returns a dict::

        {
            "ok": bool,
            "total_server": int,
            "total_local": int,
            "folders": {
                "<name>": {
                    "server": int,
                    "local": int,
                    "missing": [int, ...],
                    "cross_folder": int,
                },
                ...
            },
        }
    """
    _skip = skip_roles or set()

    provider = get_provider(account)
    async with provider.connection() as conn:
        folders = await get_or_discover_folders(conn, account.email)

        selectable = [
            f for f in folders
            if f.get("selectable", True) and f.get("role") not in _skip
        ]

        def _get_all_server_uids() -> dict[str, set[int]]:
            uids_by_folder: dict[str, set[int]] = {}
            for fi in selectable:
                name = fi["name"]
                try:
                    conn.folder.set(name, readonly=True)
                    uids_by_folder[name] = {int(u) for u in conn.uids("ALL")}
                except (imaplib.IMAP4.abort, ConnectionError, OSError):
                    raise
                except Exception:
                    log.exception("integrity_folder_error", folder=name)
                    uids_by_folder[name] = set()
            return uids_by_folder

        server_uids_map = await asyncio.to_thread(_get_all_server_uids)

        # --- Pass 1: per-folder UID comparison to find candidates -----------
        candidates: dict[str, list[int]] = {}
        local_uids_map: dict[str, set[int]] = {}

        for folder_info in selectable:
            name = folder_info["name"]
            server_uids = server_uids_map.get(name, set())
            async with db.execute(
                "SELECT uid FROM emails WHERE account_email = ? AND mailbox = ?",
                (account.email, name),
            ) as cur:
                rows = await cur.fetchall()
            local_uids = {r[0] for r in rows}
            local_uids_map[name] = local_uids

            candidate_missing = sorted(server_uids - local_uids)
            if candidate_missing:
                candidates[name] = candidate_missing

        # --- Pass 2: resolve cross-folder duplicates (Gmail labels) ---------
        cross_folder_map: dict[str, set[int]] = {}

        if candidates:
            async with db.execute(
                "SELECT message_id FROM emails WHERE account_email = ?",
                (account.email,),
            ) as cur:
                rows = await cur.fetchall()
            all_local_msgids = {r[0] for r in rows}

            def _fetch_candidate_msgids() -> dict[str, dict[int, str]]:
                out: dict[str, dict[int, str]] = {}
                for name, uid_list in candidates.items():
                    conn.folder.set(name, readonly=True)
                    uid_to_msgid: dict[int, str] = {}
                    for i in range(0, len(uid_list), 500):
                        chunk = uid_list[i:i + 500]
                        uid_str = ",".join(str(u) for u in chunk)
                        try:
                            for msg in conn.fetch(
                                AND(uid=uid_str), headers_only=True,
                                mark_seen=False, bulk=50,
                            ):
                                hdr = msg.headers.get("message-id", ("",))
                                uid_to_msgid[int(msg.uid)] = hdr[0] if hdr else ""
                        except (imaplib.IMAP4.abort, ConnectionError, OSError):
                            raise
                    out[name] = uid_to_msgid
                return out

            candidate_msgids = await asyncio.to_thread(_fetch_candidate_msgids)

            for name, uid_to_msgid in candidate_msgids.items():
                cross = set()
                for uid, msgid in uid_to_msgid.items():
                    if msgid and msgid in all_local_msgids:
                        cross.add(uid)
                cross_folder_map[name] = cross

    # --- Build result ---------------------------------------------------
    result: dict = {
        "ok": True,
        "total_server": 0,
        "total_local": 0,
        "folders": {},
    }

    for folder_info in selectable:
        name = folder_info["name"]
        server_uids = server_uids_map.get(name, set())
        local_uids = local_uids_map.get(name, set())
        cross_folder = cross_folder_map.get(name, set())
        truly_missing = sorted(set(candidates.get(name, [])) - cross_folder)

        result["total_server"] += len(server_uids)
        result["total_local"] += len(local_uids)
        result["folders"][name] = {
            "server": len(server_uids),
            "local": len(local_uids),
            "missing": truly_missing,
            "cross_folder": len(cross_folder),
        }
        if truly_missing:
            result["ok"] = False
            log.warning(
                "integrity_gap",
                account=account.email,
                folder=name,
                server=len(server_uids),
                local=len(local_uids),
                missing_count=len(truly_missing),
                cross_folder=len(cross_folder),
            )

    log.info(
        "integrity_check_done",
        account=account.email,
        ok=result["ok"],
        server=result["total_server"],
        local=result["total_local"],
    )
    return result
