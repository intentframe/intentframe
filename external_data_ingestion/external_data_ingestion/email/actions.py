"""Write operations: send, draft, reply, forward, flag, move, delete.

Every write is a short-lived connection:
- SMTP via aiosmtplib for sending
- IMAP via imap-tools (threaded) for draft/flag/move/delete
Each write updates the local DB and writes an event.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

import aiosmtplib
import aiosqlite
import structlog
from imap_tools import MailBox, MailMessageFlags

from .config import AccountConfig
from .db import write_event
from .folders import _classify_role
from .imap_connection import get_provider
from .models import DraftResult, SendResult

log = structlog.get_logger()


def _find_folder_by_role(mb: MailBox, role: str) -> str | None:
    """Ask the server for all folders and return the name matching *role*.

    Uses RFC 6154 special-use flags — no hardcoded folder names.
    """
    for fi in mb.folder.list():
        if _classify_role(fi.name, fi.flags) == role:
            return fi.name
    return None


def _build_message(
    from_addr: str,
    to: list[str],
    subject: str,
    body: str,
    *,
    cc: list[str] | None = None,
    in_reply_to: str = "",
    references: str = "",
    html: str = "",
) -> EmailMessage:
    """Construct a MIME email message."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    if html:
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body)

    return msg


async def send_email(
    account: AccountConfig,
    db: aiosqlite.Connection,
    to: list[str],
    subject: str,
    body: str,
    *,
    cc: list[str] | None = None,
    html: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> SendResult:
    """Send an email via SMTP and record the event."""
    msg = _build_message(
        account.email,
        to,
        subject,
        body,
        cc=cc,
        html=html,
        in_reply_to=in_reply_to,
        references=references,
    )

    try:
        await aiosmtplib.send(
            msg,
            hostname=account.smtp_host,
            port=account.smtp_port,
            username=account.email,
            password=account.password.get_secret_value(),
            use_tls=account.smtp_port == 465,
            start_tls=account.smtp_port != 465,
        )
        message_id = msg["Message-ID"] or ""
        await write_event(
            db,
            "email_sent",
            account_email=account.email,
            message_id=message_id,
            data={"to": to, "subject": subject},
        )
        log.info("email_sent", account=account.email, to=to, subject=subject)
        return SendResult(success=True, message_id=message_id)
    except Exception as exc:
        log.exception("send_failed", account=account.email)
        return SendResult(success=False, error=str(exc))


async def create_draft(
    account: AccountConfig,
    db: aiosqlite.Connection,
    to: list[str],
    subject: str,
    body: str,
    *,
    cc: list[str] | None = None,
    html: str = "",
    drafts_folder: str | None = None,
) -> DraftResult:
    """Create a draft by IMAP APPEND to the drafts folder.

    If *drafts_folder* is not given the actual folder name is auto-discovered
    from the server (e.g. ``[Gmail]/Drafts``).
    """
    msg = _build_message(account.email, to, subject, body, cc=cc, html=html)

    try:
        provider = get_provider(account)
        async with provider.connection() as mb:
            def _append():
                folder = drafts_folder or _find_folder_by_role(mb, "drafts")
                if not folder:
                    raise RuntimeError("Server has no folder with \\Drafts flag")
                mb.append(
                    msg.as_bytes(),
                    folder=folder,
                    flag_set=[MailMessageFlags.DRAFT, MailMessageFlags.SEEN],
                )
            await asyncio.to_thread(_append)
        message_id = msg["Message-ID"] or ""
        await write_event(
            db,
            "draft_created",
            account_email=account.email,
            message_id=message_id,
            data={"to": to, "subject": subject},
        )
        log.info("draft_created", account=account.email, subject=subject)
        return DraftResult(success=True)
    except Exception as exc:
        log.exception("create_draft_failed", account=account.email)
        return DraftResult(success=False, error=str(exc))


async def reply(
    account: AccountConfig,
    db: aiosqlite.Connection,
    original_message_id: str,
    body: str,
    *,
    html: str = "",
    reply_all: bool = False,
    as_draft: bool = False,
    drafts_folder: str | None = None,
) -> SendResult | DraftResult:
    """Reply to an email. Builds proper In-Reply-To/References chain."""
    async with db.execute(
        """SELECT message_id, subject, sender_email, to_recipients, cc_recipients,
                  in_reply_to, references_hdr
           FROM emails WHERE message_id = ? AND account_email = ?""",
        (original_message_id, account.email),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return SendResult(success=False, error=f"Original email {original_message_id} not found")

    to_addrs = [row["sender_email"]]
    cc_addrs: list[str] = []
    if reply_all:
        for r in json.loads(row["to_recipients"] or "[]"):
            if r.get("email") and r["email"] != account.email:
                to_addrs.append(r["email"])
        for r in json.loads(row["cc_recipients"] or "[]"):
            if r.get("email") and r["email"] != account.email:
                cc_addrs.append(r["email"])

    subject = row["subject"]
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    refs = (row["references_hdr"] or "").strip()
    if refs:
        references = f"{refs} {row['message_id']}"
    else:
        references = row["message_id"]

    if as_draft:
        return await create_draft(
            account,
            db,
            to_addrs,
            subject,
            body,
            cc=cc_addrs or None,
            html=html,
            drafts_folder=drafts_folder,
        )
    return await send_email(
        account,
        db,
        to_addrs,
        subject,
        body,
        cc=cc_addrs or None,
        html=html,
        in_reply_to=row["message_id"],
        references=references,
    )


async def forward(
    account: AccountConfig,
    db: aiosqlite.Connection,
    original_message_id: str,
    to: list[str],
    body: str = "",
    *,
    html: str = "",
    as_draft: bool = False,
    drafts_folder: str | None = None,
) -> SendResult | DraftResult:
    """Forward an email with its body quoted."""
    async with db.execute(
        "SELECT subject, sender_raw, date, body_plain FROM emails WHERE message_id = ? AND account_email = ?",
        (original_message_id, account.email),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return SendResult(success=False, error=f"Original email {original_message_id} not found")

    subject = row["subject"]
    if not subject.lower().startswith("fwd:"):
        subject = f"Fwd: {subject}"

    quoted = (
        f"\n\n---------- Forwarded message ----------\n"
        f"From: {row['sender_raw']}\n"
        f"Date: {row['date']}\n"
        f"Subject: {row['subject']}\n\n"
        f"{row['body_plain']}"
    )
    full_body = f"{body}{quoted}" if body else quoted.lstrip("\n")

    if as_draft:
        return await create_draft(
            account, db, to, subject, full_body, html=html, drafts_folder=drafts_folder,
        )
    return await send_email(account, db, to, subject, full_body, html=html)


async def mark_read(
    account: AccountConfig,
    db: aiosqlite.Connection,
    message_id: str,
    *,
    read: bool = True,
) -> None:
    """Set or unset the \\Seen flag on a message."""
    async with db.execute(
        "SELECT uid, mailbox FROM emails WHERE message_id = ? AND account_email = ?",
        (message_id, account.email),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return

    uid, mailbox = str(row["uid"]), row["mailbox"]

    provider = get_provider(account)
    async with provider.connection() as mb:
        def _flag():
            mb.folder.set(mailbox)
            mb.flag([uid], [MailMessageFlags.SEEN], read)
        await asyncio.to_thread(_flag)

    new_flags = await _update_local_flags(db, message_id, account.email, "\\Seen", add=read)
    await write_event(
        db,
        "flag_changed",
        account_email=account.email,
        message_id=message_id,
        data={"flag": "\\Seen", "value": read},
    )


async def move_email(
    account: AccountConfig,
    db: aiosqlite.Connection,
    message_id: str,
    to_folder: str,
) -> None:
    """Move a message to a different IMAP folder."""
    async with db.execute(
        "SELECT uid, mailbox FROM emails WHERE message_id = ? AND account_email = ?",
        (message_id, account.email),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return

    uid, old_mailbox = str(row["uid"]), row["mailbox"]

    provider = get_provider(account)
    async with provider.connection() as mb:
        def _move() -> int | None:
            from imap_tools import AND, H

            mb.folder.set(old_mailbox)
            mb.move([uid], to_folder)
            mb.folder.set(to_folder)
            for msg in mb.fetch(AND(header=H("Message-ID", message_id)), mark_seen=False, limit=1):
                return int(msg.uid) if msg.uid else None
            return None

        new_uid = await asyncio.to_thread(_move)

    update_fields = {"mailbox": to_folder}
    if new_uid is not None:
        update_fields["uid"] = new_uid

    set_clause = ", ".join(f"{k} = ?" for k in update_fields)
    await db.execute(
        f"UPDATE emails SET {set_clause} WHERE message_id = ? AND account_email = ?",
        (*update_fields.values(), message_id, account.email),
    )
    await db.commit()

    await write_event(
        db,
        "email_moved",
        account_email=account.email,
        message_id=message_id,
        data={"from": old_mailbox, "to": to_folder, "new_uid": new_uid},
    )


async def delete_email(
    account: AccountConfig,
    db: aiosqlite.Connection,
    message_id: str,
) -> None:
    """Delete a message via IMAP and remove from local DB."""
    async with db.execute(
        "SELECT uid, mailbox FROM emails WHERE message_id = ? AND account_email = ?",
        (message_id, account.email),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return

    uid, mailbox = str(row["uid"]), row["mailbox"]

    provider = get_provider(account)
    async with provider.connection() as mb:
        def _delete():
            mb.folder.set(mailbox)
            mb.delete([uid])
        await asyncio.to_thread(_delete)

    await db.execute(
        "DELETE FROM emails WHERE message_id = ? AND account_email = ?",
        (message_id, account.email),
    )
    await db.commit()

    await write_event(
        db,
        "email_deleted",
        account_email=account.email,
        message_id=message_id,
    )


async def _update_local_flags(
    db: aiosqlite.Connection,
    message_id: str,
    account_email: str,
    flag: str,
    *,
    add: bool,
) -> list[str]:
    """Update the flags JSON array for a message in the local DB."""
    async with db.execute(
        "SELECT flags FROM emails WHERE message_id = ? AND account_email = ?",
        (message_id, account_email),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return []

    flags: list[str] = json.loads(row["flags"] or "[]")
    if add and flag not in flags:
        flags.append(flag)
    elif not add and flag in flags:
        flags.remove(flag)

    await db.execute(
        "UPDATE emails SET flags = ? WHERE message_id = ? AND account_email = ?",
        (json.dumps(flags), message_id, account_email),
    )
    await db.commit()
    return flags
