#!/usr/bin/env python3
"""Manual Gmail validation script.

This is a standalone script for validating the core IMAP/SMTP behaviors we
need before building a dedicated email sync service:

1. Connect to Gmail over IMAP.
2. Fetch the last N messages from a mailbox.
3. Read the full contents of one Gmail thread.
4. Send a test email over SMTP.
5. Find a message with attachments and download its first attachment.

Usage:
    python external_data_ingestion/email/tests/test_gmail.py \
        --email you@gmail.com \
        --password "<gmail app password>"

Notes:
    - For Gmail, use an app password if 2FA is enabled.
    - The script sends the test message to your own address by default.
    - The attachment download is limited to recent messages to keep the test
      bounded and fast.
"""

from __future__ import annotations

import argparse
import email
import getpass
import imaplib
import os
import re
import smtplib
import ssl
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.header import decode_header
from email.message import EmailMessage
from pathlib import Path

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

UID_RE = re.compile(rb"\bUID (\d+)\b")
THREAD_RE = re.compile(rb"\bX-GM-THRID (\d+)\b")
MAILBOX_RE = re.compile(rb'"([^"]+)"\s*$')
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(slots=True)
class MessageSummary:
    sequence_id: str
    uid: str | None
    thread_id: str | None
    subject: str
    sender: str
    date: str
    message_id: str


def decode_header_value(value: str | bytes | None) -> str:
    """Decode RFC 2047 header values into readable text."""
    if value is None:
        return ""
    parts: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(part))
    return "".join(parts).strip()


def ensure_ok(status: str, action: str, data: object | None = None) -> None:
    """Raise a readable error when an IMAP command fails."""
    if status != "OK":
        raise RuntimeError(f"{action} failed: status={status!r}, data={data!r}")


def parse_fetch_metadata(metadata: bytes | None) -> tuple[str | None, str | None]:
    """Extract Gmail UID and thread id from IMAP FETCH metadata."""
    if not metadata:
        return None, None
    uid_match = UID_RE.search(metadata)
    thread_match = THREAD_RE.search(metadata)
    uid = uid_match.group(1).decode("ascii", errors="replace") if uid_match else None
    thread_id = thread_match.group(1).decode("ascii", errors="replace") if thread_match else None
    return uid, thread_id


def sanitize_filename(value: str) -> str:
    """Keep filenames predictable and safe for local downloads."""
    cleaned = SAFE_FILENAME_RE.sub("_", value).strip("._")
    return cleaned or "attachment.bin"


def quote_mailbox_for_imap(mailbox: str) -> str:
    """Quote mailbox name for IMAP when it contains spaces (RFC 3501).

    imaplib does not auto-quote; unquoted names with spaces cause
    'Could not parse command' from the server.
    """
    # Replace non-breaking space and other problematic chars with ASCII space
    sanitized = mailbox.replace("\xa0", " ").encode("ascii", errors="replace").decode("ascii")
    if " " in sanitized or '"' in sanitized:
        escaped = sanitized.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return sanitized


def extract_mailboxes(imap: imaplib.IMAP4_SSL) -> list[str]:
    """List mailbox names so we can prefer Gmail All Mail when available."""
    status, data = imap.list()
    ensure_ok(status, "LIST", data)
    mailboxes: list[str] = []
    for entry in data:
        if not entry:
            continue
        match = MAILBOX_RE.search(entry)
        if match:
            mailboxes.append(match.group(1).decode("utf-8", errors="replace"))
    return mailboxes


def choose_thread_mailbox(mailboxes: list[str], fallback: str) -> str:
    """Prefer All Mail so Gmail thread search can see the whole conversation."""
    for candidate in ("[Gmail]/All Mail", "[Google Mail]/All Mail"):
        if candidate in mailboxes:
            return candidate
    return fallback


def connect_imap(username: str, password: str) -> imaplib.IMAP4_SSL:
    """Open and authenticate an IMAP SSL connection."""
    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=context)
    status, data = imap.login(username, password)
    ensure_ok(status, "IMAP LOGIN", data)
    return imap


def connect_smtp(username: str, password: str) -> smtplib.SMTP_SSL:
    """Open and authenticate an SMTP SSL connection."""
    context = ssl.create_default_context()
    smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context)
    smtp.login(username, password)
    return smtp


def fetch_recent_summaries(
    imap: imaplib.IMAP4_SSL,
    mailbox: str,
    limit: int,
) -> list[MessageSummary]:
    """Fetch the last N messages with Gmail UID/thread metadata."""
    quoted = quote_mailbox_for_imap(mailbox)
    status, data = imap.select(quoted, readonly=True)
    ensure_ok(status, f"SELECT {mailbox}", data)

    status, data = imap.search(None, "ALL")
    ensure_ok(status, f"SEARCH ALL in {mailbox}", data)
    ids = data[0].split() if data and data[0] else []
    recent_ids = ids[-limit:]

    summaries: list[MessageSummary] = []
    for sequence_id in reversed(recent_ids):
        status, fetch_data = imap.fetch(
            sequence_id,
            "(UID X-GM-THRID BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])",
        )
        ensure_ok(status, f"FETCH summary for message {sequence_id!r}", fetch_data)
        if not fetch_data or not isinstance(fetch_data[0], tuple):
            continue
        metadata, header_bytes = fetch_data[0]
        uid, thread_id = parse_fetch_metadata(metadata)
        message = email.message_from_bytes(header_bytes, policy=policy.default)
        summaries.append(
            MessageSummary(
                sequence_id=sequence_id.decode("ascii", errors="replace"),
                uid=uid,
                thread_id=thread_id,
                subject=decode_header_value(message.get("Subject")),
                sender=decode_header_value(message.get("From")),
                date=decode_header_value(message.get("Date")),
                message_id=decode_header_value(message.get("Message-ID")),
            )
        )
    return summaries


def message_body_parts(message: EmailMessage) -> tuple[str, str]:
    """Extract text/plain and text/html bodies from a parsed email."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        if disposition == "attachment":
            continue
        content_type = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            payload = raw.decode(charset, errors="replace")
        if not isinstance(payload, str):
            continue
        if content_type == "text/plain":
            plain_parts.append(payload)
        elif content_type == "text/html":
            html_parts.append(payload)
    return "\n".join(plain_parts).strip(), "\n".join(html_parts).strip()


def fetch_full_message_by_sequence(
    imap: imaplib.IMAP4_SSL,
    sequence_id: str | bytes,
) -> EmailMessage:
    """Fetch a full RFC822 message by IMAP sequence number."""
    seq_str = sequence_id.decode("ascii", errors="replace") if isinstance(sequence_id, bytes) else str(sequence_id)
    status, fetch_data = imap.fetch(seq_str, "(RFC822)")
    ensure_ok(status, f"FETCH RFC822 for message {seq_str}", fetch_data)
    if not fetch_data or not isinstance(fetch_data[0], tuple):
        raise RuntimeError(f"No RFC822 payload returned for message {sequence_id}")
    return email.message_from_bytes(fetch_data[0][1], policy=policy.default)


def fetch_thread_messages(
    imap: imaplib.IMAP4_SSL,
    mailbox: str,
    thread_id: str | None,
    fallback_sequence_id: str,
) -> list[EmailMessage]:
    """Fetch all messages in the same Gmail thread, or fallback to one message."""
    quoted = quote_mailbox_for_imap(mailbox)
    status, data = imap.select(quoted, readonly=True)
    ensure_ok(status, f"SELECT {mailbox}", data)

    if not thread_id:
        return [fetch_full_message_by_sequence(imap, fallback_sequence_id)]

    status, data = imap.search(None, "X-GM-THRID", thread_id)
    if status != "OK" or not data or not data[0]:
        return [fetch_full_message_by_sequence(imap, fallback_sequence_id)]

    thread_sequence_ids = data[0].split()
    messages: list[EmailMessage] = []
    for seq_bytes in thread_sequence_ids:
        seq_str = seq_bytes.decode("ascii", errors="replace")
        status, fetch_data = imap.fetch(seq_str, "(RFC822)")
        ensure_ok(status, f"FETCH RFC822 for thread message {seq_str!r}", fetch_data)
        if not fetch_data or not isinstance(fetch_data[0], tuple):
            continue
        messages.append(email.message_from_bytes(fetch_data[0][1], policy=policy.default))
    return messages


def format_thread_preview(messages: list[EmailMessage]) -> str:
    """Render a compact human-readable preview of a thread."""
    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        subject = decode_header_value(message.get("Subject"))
        sender = decode_header_value(message.get("From"))
        date = decode_header_value(message.get("Date"))
        plain_body, html_body = message_body_parts(message)
        body = plain_body or html_body or ""
        preview = body.replace("\r", " ").replace("\n", " ").strip()
        preview = preview[:220] + ("..." if len(preview) > 220 else "")
        lines.append(
            f"[{index}] {date} | {sender} | {subject}\n"
            f"    body_preview={preview or '<empty>'}"
        )
    return "\n".join(lines)


def send_test_email(username: str, password: str, send_to: str) -> str:
    """Send a small test message over Gmail SMTP and return its subject."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"[intentframe-gmail-test] SMTP validation {now}"

    message = EmailMessage()
    message["From"] = username
    message["To"] = send_to
    message["Subject"] = subject
    message.set_content(
        "This is an automated Gmail validation message from "
        "external_data_ingestion/email/tests/test_gmail.py"
    )

    with connect_smtp(username, password) as smtp:
        smtp.send_message(message)

    return subject


def find_and_download_first_attachment(
    imap: imaplib.IMAP4_SSL,
    mailbox: str,
    search_limit: int,
    output_dir: Path,
) -> tuple[MessageSummary, Path]:
    """Find the first recent email with attachments and save its first attachment."""
    quoted = quote_mailbox_for_imap(mailbox)
    status, data = imap.select(quoted, readonly=True)
    ensure_ok(status, f"SELECT {mailbox}", data)

    status, data = imap.search(None, "ALL")
    ensure_ok(status, f"SEARCH ALL in {mailbox}", data)
    ids = data[0].split() if data and data[0] else []
    candidate_ids = ids[-search_limit:]

    for sequence_id in reversed(candidate_ids):
        status, fetch_data = imap.fetch(sequence_id, "(UID X-GM-THRID RFC822)")
        ensure_ok(status, f"FETCH RFC822 for attachment scan {sequence_id!r}", fetch_data)
        if not fetch_data or not isinstance(fetch_data[0], tuple):
            continue
        metadata, raw_message = fetch_data[0]
        uid, thread_id = parse_fetch_metadata(metadata)
        message = email.message_from_bytes(raw_message, policy=policy.default)

        attachments = [part for part in message.iter_attachments()]
        if not attachments:
            continue

        first_attachment = attachments[0]
        filename = sanitize_filename(first_attachment.get_filename() or "attachment.bin")
        payload = first_attachment.get_payload(decode=True) or b""
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / filename
        destination.write_bytes(payload)

        summary = MessageSummary(
            sequence_id=sequence_id.decode("ascii", errors="replace"),
            uid=uid,
            thread_id=thread_id,
            subject=decode_header_value(message.get("Subject")),
            sender=decode_header_value(message.get("From")),
            date=decode_header_value(message.get("Date")),
            message_id=decode_header_value(message.get("Message-ID")),
        )
        return summary, destination

    raise RuntimeError(
        f"No attachment-bearing message found in the last {search_limit} messages of {mailbox}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Define CLI flags for manual Gmail validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Gmail address")
    parser.add_argument(
        "--password",
        default=os.environ.get("GMAIL_APP_PASSWORD", ""),
        help="Gmail app password. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--mailbox",
        default="INBOX",
        help="Mailbox to inspect for recent mail and attachments. Default: INBOX",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many recent messages to fetch. Default: 10",
    )
    parser.add_argument(
        "--attachment-search-limit",
        type=int,
        default=200,
        help="How many recent messages to scan for an attachment. Default: 200",
    )
    parser.add_argument(
        "--send-to",
        default="",
        help="Recipient for the SMTP test email. Defaults to your own Gmail address.",
    )
    parser.add_argument(
        "--output-dir",
        default="downloads/gmail_test_attachments",
        help="Where to save the first downloaded attachment.",
    )
    return parser


def main() -> int:
    """Run the validation flow and print a readable summary."""
    args = build_parser().parse_args()
    password = args.password or getpass.getpass("Gmail app password: ")
    send_to = args.send_to or args.email
    output_dir = Path(args.output_dir).expanduser().resolve()

    print("== Gmail validation start ==")
    print(f"Account: {args.email}")
    print(f"Mailbox: {args.mailbox}")
    print()

    try:
        with connect_imap(args.email, password) as imap:
            mailboxes = extract_mailboxes(imap)
            thread_mailbox = choose_thread_mailbox(mailboxes, args.mailbox)

            print("[1/4] IMAP login successful")
            print(f"Discovered {len(mailboxes)} mailboxes")
            print(f"Thread mailbox: {thread_mailbox}")
            print()

            print(f"[2/4] Fetching last {args.limit} messages from {args.mailbox}")
            recent = fetch_recent_summaries(imap, args.mailbox, args.limit)
            if not recent:
                raise RuntimeError(f"No messages found in {args.mailbox}")
            for index, summary in enumerate(recent, start=1):
                print(
                    f"  {index:02d}. uid={summary.uid or '-'} "
                    f"thread={summary.thread_id or '-'} "
                    f"date={summary.date} "
                    f"from={summary.sender} "
                    f"subject={summary.subject}"
                )
            print()

            newest = recent[0]
            print("[3/4] Reading one full thread")
            print(
                f"Using message uid={newest.uid or '-'} "
                f"thread={newest.thread_id or '-'} "
                f"subject={newest.subject}"
            )
            thread_messages = fetch_thread_messages(
                imap,
                mailbox=thread_mailbox,
                thread_id=newest.thread_id,
                fallback_sequence_id=newest.sequence_id,
            )
            print(f"Thread message count: {len(thread_messages)}")
            print(format_thread_preview(thread_messages))
            print()

            print("[4/4] Looking for a message with attachments")
            attachment_owner, saved_path = find_and_download_first_attachment(
                imap,
                mailbox=args.mailbox,
                search_limit=args.attachment_search_limit,
                output_dir=output_dir,
            )
            print(
                f"Saved first attachment from subject={attachment_owner.subject!r} "
                f"to {saved_path}"
            )
            print()

        print("[SMTP] Sending a test email")
        sent_subject = send_test_email(args.email, password, send_to=send_to)
        print(f"Sent SMTP test email to {send_to} with subject: {sent_subject}")
        print()
        print("== Gmail validation completed successfully ==")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nValidation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
