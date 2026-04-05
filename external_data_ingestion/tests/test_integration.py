"""Integration tests for the email sync service (daemon + client).

Requires a real email account with an app password.

1. Fill in  external_data_ingestion/email/tests/test_config.yaml
2. Run:     uv run pytest external_data_ingestion/email/tests/test_integration.py -v -s

CLI overrides still work:
    uv run pytest ... --email you@gmail.com --password "xxxx-xxxx-xxxx-xxxx"

Tests are organised as ordered classes so they run in dependency order.
All test-generated emails use a unique subject prefix so the session-scoped
cleanup fixture can purge them from the remote server when the run finishes.
"""

from __future__ import annotations

import asyncio
import json

import pytest


# ═══════════════════════════════════════════════════════════════════
#  1. Config / Providers / DB schema
# ═══════════════════════════════════════════════════════════════════


class TestProviders:

    def test_resolve_gmail(self):
        from external_data_ingestion.email.providers import resolve_provider

        p = resolve_provider("alice@gmail.com")
        assert p.name == "gmail"
        assert p.imap_host == "imap.gmail.com"
        assert p.smtp_host == "smtp.gmail.com"
        assert p.imap_port == 993
        assert p.smtp_port == 465

    def test_resolve_outlook(self):
        from external_data_ingestion.email.providers import resolve_provider

        p = resolve_provider("bob@outlook.com")
        assert p.name == "outlook"
        assert p.imap_host == "outlook.office365.com"

    def test_resolve_unknown_falls_back(self):
        from external_data_ingestion.email.providers import resolve_provider

        p = resolve_provider("admin@example.org")
        assert p.name == "other"
        assert p.imap_host == "imap.example.org"
        assert p.smtp_host == "smtp.example.org"


class TestConfig:

    def test_service_config_loaded(self, service_config):
        assert len(service_config.accounts) == 1
        acc = service_config.accounts[0]
        assert "@" in acc.email
        assert acc.password.get_secret_value()
        assert acc.imap_host
        assert acc.smtp_host
        assert acc.imap_port > 0
        assert acc.smtp_port > 0

    def test_db_path_is_temp(self, service_config, tmp_workspace):
        assert str(service_config.db_path).startswith(str(tmp_workspace))


class TestDBSchema:

    async def test_required_tables_exist(self, db):
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            tables = {row[0] for row in await cur.fetchall()}

        for name in ("accounts", "emails", "attachments", "folders", "sync_state", "events", "schema_version"):
            assert name in tables, f"Missing table: {name}"

    async def test_fts_virtual_table(self, db):
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='emails_fts'"
        ) as cur:
            assert await cur.fetchone() is not None

    async def test_wal_mode_active(self, db):
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
        assert row[0].lower() == "wal"

    async def test_foreign_keys_on(self, db):
        async with db.execute("PRAGMA foreign_keys") as cur:
            row = await cur.fetchone()
        assert row[0] == 1


# ═══════════════════════════════════════════════════════════════════
#  2. Folder discovery
# ═══════════════════════════════════════════════════════════════════


class TestFolderDiscovery:

    async def test_discover_folders_returns_inbox(self, discovered_folders):
        assert len(discovered_folders) > 0
        roles = {f["role"] for f in discovered_folders if f["role"]}
        assert "inbox" in roles, f"Expected 'inbox' role. Got: {roles}"

        print(f"\n  {len(discovered_folders)} folders discovered:")
        for f in discovered_folders:
            print(f"    {f['name']:30s}  role={f['role']}")

    async def test_discover_has_common_gmail_roles(self, discovered_folders):
        roles = {f["role"] for f in discovered_folders if f["role"]}
        for expected in ("inbox", "sent", "drafts", "trash"):
            if expected not in roles:
                print(f"  NOTE: '{expected}' role not found (may vary by provider)")


# ═══════════════════════════════════════════════════════════════════
#  3. Sync (full + incremental)
# ═══════════════════════════════════════════════════════════════════


class TestSync:

    async def test_full_inbox_sync(self, account, db, attachments_dir):
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)
        async with provider.connection() as mb:
            inserted = await sync_folder(account, "INBOX", db, attachments_dir, full=True, mb=mb)

        async with db.execute(
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = 'INBOX'",
            (account.email,),
        ) as cur:
            total = (await cur.fetchone())[0]

        print(f"\n  Full sync: {inserted} new, {total} total in INBOX")
        assert total >= 0

    async def test_sync_state_persisted(self, account, db):
        async with db.execute(
            "SELECT uidvalidity, last_uid, message_count FROM sync_state "
            "WHERE account_email = ? AND mailbox = 'INBOX'",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        assert row is not None, "sync_state row missing for INBOX"
        assert row["uidvalidity"] > 0
        print(f"  sync_state: uidvalidity={row['uidvalidity']}, last_uid={row['last_uid']}")

    async def test_incremental_sync_idempotent(self, account, db, attachments_dir):
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)
        async with provider.connection() as mb:
            count = await sync_folder(account, "INBOX", db, attachments_dir, mb=mb)
        print(f"  Incremental sync: {count} new (expected 0 or very few)")

    async def test_events_written(self, db):
        async with db.execute("SELECT COUNT(*) FROM events") as cur:
            total = (await cur.fetchone())[0]
        print(f"  Events in DB after sync: {total}")
        assert total >= 0

    async def test_headers_raw_populated(self, account, db):
        """After sync, synced emails should have raw RFC822 headers stored."""
        async with db.execute(
            "SELECT headers_raw FROM emails WHERE account_email = ? AND headers_raw != '' LIMIT 1",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        assert row is not None, "Expected at least one email with headers_raw populated"
        headers = row["headers_raw"]
        assert len(headers) > 50, f"headers_raw too short ({len(headers)} chars)"
        assert ":" in headers, "headers_raw should contain header lines with colons"
        print(f"  headers_raw: {len(headers)} chars (first 120: {headers[:120]}...)")


# ═══════════════════════════════════════════════════════════════════
#  4. Send email (to self)
# ═══════════════════════════════════════════════════════════════════


class TestSendEmail:

    async def test_send_to_self(self, account, db, email_address, subject_prefix):
        from external_data_ingestion.email.actions import send_email

        subject = f"{subject_prefix} send_test"
        result = await send_email(
            account, db,
            to=[email_address],
            subject=subject,
            body="Body of the send_test email.\nLine two.",
        )
        assert result.success, f"Send failed: {result.error}"
        assert result.message_id
        print(f"\n  Sent: {result.message_id}")

    async def test_send_with_html(self, account, db, email_address, subject_prefix):
        from external_data_ingestion.email.actions import send_email

        subject = f"{subject_prefix} html_test"
        result = await send_email(
            account, db,
            to=[email_address],
            subject=subject,
            body="Plain-text fallback.",
            html="<h1>HTML body</h1><p>Paragraph with <b>bold</b>.</p>",
        )
        assert result.success, f"Send failed: {result.error}"
        print(f"  Sent HTML email: {result.message_id}")

    async def test_send_event_recorded(self, db):
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'email_sent'"
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count >= 1


# ═══════════════════════════════════════════════════════════════════
#  5. Wait for delivery + re-sync
# ═══════════════════════════════════════════════════════════════════


class TestDeliveryAndResync:

    async def test_sent_email_arrives_in_inbox(
        self, account, db, attachments_dir, subject_prefix
    ):
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)
        target_subject = f"{subject_prefix} send_test"
        found = False

        for attempt in range(18):
            await asyncio.sleep(5)
            async with provider.connection() as mb:
                await sync_folder(account, "INBOX", db, attachments_dir, mb=mb)
            async with db.execute(
                "SELECT message_id FROM emails WHERE subject LIKE ? AND account_email = ?",
                (f"%{target_subject}%", account.email),
            ) as cur:
                row = await cur.fetchone()
            if row:
                found = True
                print(f"\n  Arrived after {(attempt + 1) * 5}s: {row['message_id']}")
                break
            print(f"  Waiting for delivery... attempt {attempt + 1}/18")

        assert found, (
            f"Test email '{target_subject}' never arrived in INBOX after 90s. "
            "Check that the account allows SMTP send and IMAP receive."
        )


# ═══════════════════════════════════════════════════════════════════
#  6. Reply and Forward
# ═══════════════════════════════════════════════════════════════════


class TestReplyForward:

    async def _get_test_message_id(self, db, account_email: str, subject_prefix: str) -> str:
        async with db.execute(
            "SELECT message_id FROM emails "
            "WHERE subject LIKE ? AND account_email = ? LIMIT 1",
            (f"%{subject_prefix} send_test%", account_email),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            pytest.skip("Original send_test email not found in DB")
        return row["message_id"]

    async def test_reply(self, account, db, subject_prefix):
        from external_data_ingestion.email.actions import reply

        msg_id = await self._get_test_message_id(db, account.email, subject_prefix)
        result = await reply(account, db, msg_id, body="Reply body from integration test.")
        assert result.success, f"Reply failed: {getattr(result, 'error', '')}"
        print(f"\n  Replied to {msg_id}")

    async def test_forward(self, account, db, email_address, subject_prefix):
        from external_data_ingestion.email.actions import forward

        msg_id = await self._get_test_message_id(db, account.email, subject_prefix)
        result = await forward(
            account, db, msg_id,
            to=[email_address],
            body="Forwarded by integration test.",
        )
        assert result.success, f"Forward failed: {getattr(result, 'error', '')}"
        print(f"  Forwarded {msg_id} to {email_address}")


# ═══════════════════════════════════════════════════════════════════
#  7. Draft
# ═══════════════════════════════════════════════════════════════════


class TestDraft:

    async def test_create_draft(self, account, db, email_address, subject_prefix):
        from external_data_ingestion.email.actions import create_draft

        subject = f"{subject_prefix} draft_test"
        result = await create_draft(
            account, db,
            to=[email_address],
            subject=subject,
            body="This is a draft from the integration test.",
        )
        assert result.success, f"Draft creation failed: {result.error}"
        print(f"\n  Draft created: {subject}")

    async def test_draft_event_recorded(self, db):
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'draft_created'"
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count >= 1


# ═══════════════════════════════════════════════════════════════════
#  8. Mark read / unread
# ═══════════════════════════════════════════════════════════════════


class TestFlagOperations:

    async def test_mark_read_then_unread(self, account, db):
        async with db.execute(
            "SELECT message_id FROM emails "
            "WHERE account_email = ? AND mailbox = 'INBOX' LIMIT 1",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No emails in INBOX to flag")

        from external_data_ingestion.email.actions import mark_read

        msg_id = row["message_id"]

        await mark_read(account, db, msg_id, read=True)
        async with db.execute(
            "SELECT flags FROM emails WHERE message_id = ?", (msg_id,)
        ) as cur:
            flags = json.loads((await cur.fetchone())["flags"])
        assert "\\Seen" in flags, f"\\Seen not set: {flags}"

        await mark_read(account, db, msg_id, read=False)
        async with db.execute(
            "SELECT flags FROM emails WHERE message_id = ?", (msg_id,)
        ) as cur:
            flags = json.loads((await cur.fetchone())["flags"])
        assert "\\Seen" not in flags, f"\\Seen still present: {flags}"

        print(f"\n  mark_read / mark_unread OK on {msg_id}")

    async def test_flag_event_recorded(self, db):
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'flag_changed'"
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count >= 1


# ═══════════════════════════════════════════════════════════════════
#  9. Client reads
# ═══════════════════════════════════════════════════════════════════


class TestClientReads:

    async def test_list_folders(self, client, email_address):
        folders = await client.list_folders(email_address)
        names = [f.name for f in folders]
        print(f"\n  list_folders: {names}")
        assert isinstance(folders, list)

    async def test_list_folders_have_roles(self, client, email_address):
        """Folders returned from the new folders table should carry role metadata."""
        folders = await client.list_folders(email_address)
        roles = {f.role for f in folders if f.role}
        print(f"  folder roles: {roles}")
        if folders:
            assert "inbox" in roles, f"Expected 'inbox' role among: {roles}"

    async def test_get_recent(self, client, email_address):
        emails = await client.get_recent(email_address, "INBOX", limit=10)
        print(f"  get_recent: {len(emails)} emails")
        for e in emails[:3]:
            print(f"    {e.date} | {e.sender_email} | {e.subject[:60]}")
        assert isinstance(emails, list)

    async def test_get_email_existing(self, client, email_address):
        db = await client._get_db()
        async with db.execute(
            "SELECT message_id FROM emails WHERE account_email = ? LIMIT 1",
            (email_address,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No emails to test")

        email_obj = await client.get_email(row["message_id"])
        assert email_obj is not None
        assert email_obj.message_id == row["message_id"]
        print(f"  get_email: {email_obj.subject[:60]}")

    async def test_get_email_nonexistent(self, client):
        result = await client.get_email("<nonexistent.id@test.invalid>")
        assert result is None

    async def test_get_unread_count(self, client, email_address):
        count = await client.get_unread_count(email_address)
        print(f"  get_unread_count: {count}")
        assert isinstance(count, int)
        assert count >= 0

    async def test_get_message_count(self, client, email_address):
        count = await client.get_message_count(email_address, "INBOX")
        print(f"  get_message_count(INBOX): {count}")
        assert isinstance(count, int)
        assert count > 0, "Expected at least 1 email in INBOX after sync"

    async def test_get_message_count_empty_mailbox(self, client, email_address):
        count = await client.get_message_count(email_address, "NONEXISTENT_FOLDER")
        assert count == 0

    async def test_get_email_headers_only_skips_body_fetch(self, client, account, db):
        """get_email(headers_only=True) should NOT trigger lazy body fetch for content_level=0 rows."""
        async with db.execute(
            "SELECT id, message_id FROM emails "
            "WHERE account_email = ? AND content_level = 1 AND body_plain != '' LIMIT 1",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No emails with body to test headers_only")

        email_id = row["id"]
        message_id = row["message_id"]

        await db.execute(
            "UPDATE emails SET body_plain = '', body_html = '', content_level = 0 WHERE id = ?",
            (email_id,),
        )
        await db.commit()

        email_obj = await client.get_email(message_id, headers_only=True)
        assert email_obj is not None
        assert email_obj.content_level == 0, (
            "headers_only=True should return the row as-is without upgrading content_level"
        )

        await db.execute(
            "UPDATE emails SET content_level = 1 WHERE id = ?",
            (email_id,),
        )
        await db.commit()
        print(f"  get_email(headers_only=True): content_level stayed 0 (no lazy fetch)")

    async def test_get_email_has_headers_raw(self, client, email_address):
        """get_email should return the headers_raw field from the DB."""
        db = await client._get_db()
        async with db.execute(
            "SELECT message_id FROM emails "
            "WHERE account_email = ? AND headers_raw != '' LIMIT 1",
            (email_address,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No emails with headers_raw to test")

        email_obj = await client.get_email(row["message_id"])
        assert email_obj is not None
        assert email_obj.headers_raw, "headers_raw should be non-empty"
        assert ":" in email_obj.headers_raw
        print(f"  get_email headers_raw: {len(email_obj.headers_raw)} chars")


# ═══════════════════════════════════════════════════════════════════
#  10. FTS search
# ═══════════════════════════════════════════════════════════════════


class TestSearch:

    async def test_fts_finds_test_email(self, client, email_address, subject_prefix):
        results = await client.search("send_test", account_email=email_address, limit=10)
        print(f"\n  search('send_test'): {len(results)} result(s)")
        assert len(results) >= 1, "FTS search should find at least our send_test email"

    async def test_fts_no_results_for_garbage(self, client, email_address):
        results = await client.search(
            "xyzzy_nonexistent_token_42", account_email=email_address
        )
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════
#  11. Thread reconstruction
# ═══════════════════════════════════════════════════════════════════


class TestThreadReconstruction:

    async def test_get_thread_on_reply(self, client, account, db, attachments_dir, email_address):
        """After reply, the replied message should share a thread with the original."""
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)
        async with provider.connection() as mb:
            await sync_folder(account, "INBOX", db, attachments_dir, mb=mb)

        async with db.execute(
            "SELECT message_id FROM emails "
            "WHERE in_reply_to != '' AND account_email = ? LIMIT 1",
            (email_address,),
        ) as cur:
            row = await cur.fetchone()

        assert row, "Expected at least one email with in_reply_to after syncing replies"

        thread = await client.get_thread(row["message_id"])
        print(f"\n  get_thread: {len(thread)} message(s) in thread")
        assert len(thread) >= 1


# ═══════════════════════════════════════════════════════════════════
#  12. Client writes (through EmailClient)
# ═══════════════════════════════════════════════════════════════════


class TestClientWrites:

    async def test_client_send(self, client, email_address, subject_prefix):
        subject = f"{subject_prefix} client_send"
        result = await client.send(
            email_address,
            to=[email_address],
            subject=subject,
            body="Sent via EmailClient.send()",
        )
        assert result.success, f"Client.send failed: {result.error}"
        print(f"\n  client.send: {result.message_id}")

    async def test_client_create_draft(self, client, email_address, subject_prefix):
        subject = f"{subject_prefix} client_draft"
        result = await client.create_draft(
            email_address,
            to=[email_address],
            subject=subject,
            body="Draft via EmailClient.create_draft()",
        )
        assert result.success, f"Client.create_draft failed: {result.error}"
        print(f"  client.create_draft: {subject}")


# ═══════════════════════════════════════════════════════════════════
#  13. Observer / event polling
# ═══════════════════════════════════════════════════════════════════


class TestObserver:

    async def test_event_listener_fires(self, client, email_address, subject_prefix):
        received: list = []

        @client.on("email_sent")
        async def _on_sent(event):
            received.append(event)

        await client.start_listening(poll_interval=0.3)

        subject = f"{subject_prefix} observer_test"
        result = await client.send(
            email_address,
            to=[email_address],
            subject=subject,
            body="Testing observer pattern",
        )
        assert result.success

        for _ in range(20):
            await asyncio.sleep(0.3)
            if received:
                break

        await client.stop_listening()

        assert len(received) >= 1, "Observer did not fire for email_sent"
        assert received[0].event_type == "email_sent"
        print(f"\n  Observer received {len(received)} event(s)")

        # Clean up: remove handler to avoid leaking into later tests
        client._handlers["email_sent"].remove(_on_sent)

    async def test_start_stop_listening_idempotent(self, client):
        await client.start_listening(poll_interval=1.0)
        await client.start_listening(poll_interval=1.0)
        await client.stop_listening()
        await client.stop_listening()


# ═══════════════════════════════════════════════════════════════════
#  14. Move email
# ═══════════════════════════════════════════════════════════════════


class TestMoveEmail:

    @staticmethod
    def _trash_folder_name(discovered_folders) -> str:
        for f in discovered_folders:
            if f["role"] == "trash":
                return f["name"]
        pytest.skip("No trash folder found for this account")

    async def test_move_to_trash_and_back(self, account, db, subject_prefix, discovered_folders):
        from external_data_ingestion.email.actions import move_email

        trash_folder = self._trash_folder_name(discovered_folders)

        async with db.execute(
            "SELECT message_id, mailbox FROM emails "
            "WHERE subject LIKE ? AND account_email = ? AND mailbox = 'INBOX' LIMIT 1",
            (f"%{subject_prefix}%", account.email),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No test email in INBOX to move")

        msg_id = row["message_id"]

        await move_email(account, db, msg_id, trash_folder)
        async with db.execute(
            "SELECT mailbox FROM emails WHERE message_id = ?", (msg_id,)
        ) as cur:
            r = await cur.fetchone()
        assert r["mailbox"] == trash_folder

        await move_email(account, db, msg_id, "INBOX")
        async with db.execute(
            "SELECT mailbox FROM emails WHERE message_id = ?", (msg_id,)
        ) as cur:
            r = await cur.fetchone()
        assert r["mailbox"] == "INBOX"

        print(f"\n  Moved {msg_id}: INBOX -> {trash_folder} -> INBOX")

    async def test_move_event_recorded(self, db):
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'email_moved'"
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count >= 1


# ═══════════════════════════════════════════════════════════════════
#  15. Delete email
# ═══════════════════════════════════════════════════════════════════


class TestDeleteEmail:

    async def test_send_then_delete(self, account, db, email_address, attachments_dir, subject_prefix):
        from external_data_ingestion.email.actions import delete_email, send_email
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)
        subject = f"{subject_prefix} delete_me"
        send_result = await send_email(
            account, db, to=[email_address], subject=subject, body="Will be deleted.",
        )
        assert send_result.success

        row = None
        for attempt in range(18):
            await asyncio.sleep(5)
            async with provider.connection() as mb:
                await sync_folder(account, "INBOX", db, attachments_dir, mb=mb)
            async with db.execute(
                "SELECT message_id FROM emails WHERE subject LIKE ?",
                (f"%{subject}%",),
            ) as cur:
                row = await cur.fetchone()
            if row:
                print(f"\n  Email arrived after {(attempt + 1) * 5}s")
                break

        if not row:
            pytest.skip("Delete-test email never arrived")

        msg_id = row["message_id"]
        await delete_email(account, db, msg_id)

        async with db.execute(
            "SELECT * FROM emails WHERE message_id = ?", (msg_id,)
        ) as cur:
            assert await cur.fetchone() is None, "Email should be gone from local DB"

        async with db.execute(
            "SELECT * FROM events WHERE event_type = 'email_deleted' AND message_id = ?",
            (msg_id,),
        ) as cur:
            assert await cur.fetchone() is not None, "Delete event should be recorded"

        print(f"  Deleted {msg_id} from remote + local")


# ═══════════════════════════════════════════════════════════════════
#  16. Daemon operations
# ═══════════════════════════════════════════════════════════════════


class TestDaemon:

    async def test_upsert_account(self, db, account):
        from external_data_ingestion.email.daemon import _upsert_account_row

        await _upsert_account_row(db, account)

        async with db.execute(
            "SELECT * FROM accounts WHERE email = ?", (account.email,)
        ) as cur:
            row = await cur.fetchone()

        assert row is not None
        assert row["provider"] == account.provider
        assert row["imap_host"] == account.imap_host
        assert row["status"] == "active"
        print(f"\n  Account upserted: {account.email}")

    async def test_upsert_folders_populates_table(self, db, account, discovered_folders):
        from external_data_ingestion.email.daemon import _upsert_folders

        await _upsert_folders(db, account.email, discovered_folders)

        async with db.execute(
            "SELECT COUNT(*) FROM folders WHERE account_email = ?", (account.email,)
        ) as cur:
            count = (await cur.fetchone())[0]

        assert count == len(discovered_folders), (
            f"Expected {len(discovered_folders)} rows in folders table, got {count}"
        )

        async with db.execute(
            "SELECT name, role FROM folders WHERE account_email = ? AND role IS NOT NULL",
            (account.email,),
        ) as cur:
            rows = await cur.fetchall()

        roles = {r["role"] for r in rows}
        assert "inbox" in roles, f"Expected 'inbox' role in folders table. Got: {roles}"
        print(f"\n  _upsert_folders: {count} folders inserted, roles={roles}")

    async def test_upsert_folders_idempotent(self, db, account, discovered_folders):
        from external_data_ingestion.email.daemon import _upsert_folders

        await _upsert_folders(db, account.email, discovered_folders)
        await _upsert_folders(db, account.email, discovered_folders)

        async with db.execute(
            "SELECT COUNT(*) FROM folders WHERE account_email = ?", (account.email,)
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count == len(discovered_folders), "Duplicate inserts should not create extra rows"

    async def test_upsert_idempotent(self, db, account):
        from external_data_ingestion.email.daemon import _upsert_account_row

        await _upsert_account_row(db, account)
        await _upsert_account_row(db, account)

        async with db.execute("SELECT COUNT(*) FROM accounts WHERE email = ?", (account.email,)) as cur:
            count = (await cur.fetchone())[0]
        assert count == 1

    async def test_sync_all_folders(self, account, db, attachments_dir):
        from external_data_ingestion.email.sync import sync_all_folders

        total = await sync_all_folders(account, db, attachments_dir)
        print(f"\n  sync_all_folders: {total} new messages")

        async with db.execute(
            "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
        ) as cur:
            for r in await cur.fetchall():
                print(f"    {r['event_type']}: {r['cnt']}")

    async def test_daemon_graceful_shutdown(self, service_config):
        """Start the real SyncDaemon, stop it, verify clean exit.

        The daemon now runs a priority-first startup:
        1. Priority pass: INBOX + Sent full content (SINCE body_sync_days)
        2. Spawns IDLE + periodic + backfill tasks
        """
        from external_data_ingestion.email.daemon import SyncDaemon

        daemon = SyncDaemon(service_config)
        await daemon.start()
        await asyncio.sleep(3)
        daemon.request_stop()
        await daemon.wait_stopped(timeout=15)

        assert not daemon.is_running
        print("\n  Daemon started + shut down cleanly")



# ═══════════════════════════════════════════════════════════════════
#  17. Multi-account storage isolation
# ═══════════════════════════════════════════════════════════════════


class TestMultiAccountStorage:
    """Verify that two accounts can store the same message_id independently."""

    FAKE_MSG_ID = "<shared-msg@example.com>"
    ACCT_A = "alice@test.local"
    ACCT_B = "bob@test.local"

    async def test_same_message_id_two_accounts(self, db):
        """Insert the same message_id for two different accounts."""
        import json as _json

        for acct in (self.ACCT_A, self.ACCT_B):
            await db.execute(
                """INSERT OR IGNORE INTO emails
                   (uid, message_id, account_email, mailbox, subject,
                    to_recipients, cc_recipients, flags)
                   VALUES (?, ?, ?, 'INBOX', ?, '[]', '[]', '[]')""",
                (1, self.FAKE_MSG_ID, acct, f"Test from {acct}"),
            )
        await db.commit()

        async with db.execute(
            "SELECT account_email, subject FROM emails WHERE message_id = ? ORDER BY account_email",
            (self.FAKE_MSG_ID,),
        ) as cur:
            rows = await cur.fetchall()

        assert len(rows) == 2, f"Expected 2 rows for same message_id, got {len(rows)}"
        accounts = {r["account_email"] for r in rows}
        assert accounts == {self.ACCT_A, self.ACCT_B}
        print(f"\n  Same message_id stored for {len(rows)} accounts")

    async def test_flag_update_scoped_to_account(self, db):
        """Updating flags on one account must not affect the other."""
        import json as _json

        from external_data_ingestion.email.actions import _update_local_flags

        await _update_local_flags(db, self.FAKE_MSG_ID, self.ACCT_A, "\\Seen", add=True)

        async with db.execute(
            "SELECT flags FROM emails WHERE message_id = ? AND account_email = ?",
            (self.FAKE_MSG_ID, self.ACCT_A),
        ) as cur:
            row_a = await cur.fetchone()

        async with db.execute(
            "SELECT flags FROM emails WHERE message_id = ? AND account_email = ?",
            (self.FAKE_MSG_ID, self.ACCT_B),
        ) as cur:
            row_b = await cur.fetchone()

        flags_a = _json.loads(row_a["flags"])
        flags_b = _json.loads(row_b["flags"])
        assert "\\Seen" in flags_a, f"Account A should have \\Seen: {flags_a}"
        assert "\\Seen" not in flags_b, f"Account B should NOT have \\Seen: {flags_b}"
        print("  Flag update scoped correctly")

    async def test_delete_scoped_to_account(self, db):
        """Deleting from one account must not remove the other's copy."""
        await db.execute(
            "DELETE FROM emails WHERE message_id = ? AND account_email = ?",
            (self.FAKE_MSG_ID, self.ACCT_A),
        )
        await db.commit()

        async with db.execute(
            "SELECT COUNT(*) FROM emails WHERE message_id = ?",
            (self.FAKE_MSG_ID,),
        ) as cur:
            count = (await cur.fetchone())[0]

        assert count == 1, f"Expected 1 remaining row, got {count}"

        async with db.execute(
            "SELECT account_email FROM emails WHERE message_id = ?",
            (self.FAKE_MSG_ID,),
        ) as cur:
            row = await cur.fetchone()

        assert row["account_email"] == self.ACCT_B
        print("  Delete scoped correctly")

        await db.execute(
            "DELETE FROM emails WHERE message_id = ? AND account_email = ?",
            (self.FAKE_MSG_ID, self.ACCT_B),
        )
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
#  18. Account management (config CRUD)
# ═══════════════════════════════════════════════════════════════════


class TestAccountManagement:

    async def test_add_email_no_validate(self, email_home):
        from external_data_ingestion.email.config import (
            _read_raw_config,
            _write_config_atomic,
            list_configured_emails,
        )

        raw, path = _read_raw_config()
        raw["accounts"].append({"email": "fake-test@example.org", "display_name": "Fake User"})
        _write_config_atomic(raw, path)

        emails = list_configured_emails()
        assert "fake-test@example.org" in emails
        print(f"\n  add_email (config CRUD): {emails}")

    async def test_add_email_idempotent(self, email_home):
        from external_data_ingestion.email.config import (
            _read_raw_config,
            _write_config_atomic,
            list_configured_emails,
        )

        raw, path = _read_raw_config()
        raw["accounts"] = [a for a in raw["accounts"] if a.get("email") != "fake-test@example.org"]
        raw["accounts"].append({"email": "fake-test@example.org"})
        _write_config_atomic(raw, path)

        emails = list_configured_emails()
        assert emails.count("fake-test@example.org") == 1
        print("  add_email idempotent (update, no duplicate)")

    async def test_remove_email(self, email_home):
        from external_data_ingestion.email.config import list_configured_emails, remove_email

        assert remove_email("fake-test@example.org") is True
        assert "fake-test@example.org" not in list_configured_emails()
        print("  remove_email OK")

    async def test_remove_nonexistent(self, email_home):
        from external_data_ingestion.email.config import remove_email

        assert remove_email("nobody@nowhere.invalid") is False
        print("  remove_email returns False for unknown")

    async def test_list_configured_emails(self, email_home, email_address):
        from external_data_ingestion.email.config import list_configured_emails

        emails = list_configured_emails()
        assert email_address in emails
        print(f"  list_configured_emails: {emails}")

    async def test_client_list_accounts(self, client, email_address):
        accounts = await client.list_accounts()
        account_emails = [a.email for a in accounts]
        assert email_address in account_emails
        print(f"  client.list_accounts: {account_emails}")


# ═══════════════════════════════════════════════════════════════════
#  19. Tiered sync: schema, headers-only, body upgrade, lazy fetch
# ═══════════════════════════════════════════════════════════════════


class TestTieredSyncSchema:
    """Verify the content_level column exists and behaves correctly."""

    async def test_content_level_column_exists(self, db):
        async with db.execute("PRAGMA table_info(emails)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        assert "content_level" in cols
        print("\n  content_level column exists in emails table")

    async def test_schema_version_is_3(self, db):
        async with db.execute("SELECT version FROM schema_version LIMIT 1") as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == 3
        print(f"  schema_version = {row[0]}")

    async def test_full_sync_rows_have_content_level_1(self, db, account):
        """Emails inserted by the earlier full sync should have content_level=1."""
        async with db.execute(
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND content_level = 1",
            (account.email,),
        ) as cur:
            count = (await cur.fetchone())[0]
        assert count > 0, "Full-sync emails should have content_level=1"
        print(f"  {count} emails with content_level=1 from full sync")


class TestHeadersOnlySync:
    """Verify that headers_only sync produces content_level=0 rows."""

    async def test_extract_email_row_headers_only(self):
        """Unit-level check: _extract_email_row with headers_only=True sets content_level=0."""
        from unittest.mock import MagicMock

        from external_data_ingestion.email.sync import _extract_email_row

        msg = MagicMock()
        msg.from_values = MagicMock(email="a@b.com", name="A", full="A <a@b.com>")
        msg.to_values = []
        msg.cc_values = []
        msg.headers = {"message-id": ("<test@id>",)}
        msg.date = MagicMock(year=2025, isoformat=lambda: "2025-01-01T00:00:00")
        msg.subject = "Test"
        msg.text = "Body text"
        msg.html = "<p>HTML</p>"
        msg.flags = ()
        msg.size_rfc822 = 1000
        msg.size = 1000
        msg.attachments = []
        msg.uid = "42"
        msg.obj = None

        row = _extract_email_row(msg, "test@x.com", "INBOX", headers_only=True)
        assert row["content_level"] == 0
        assert row["body_plain"] == ""
        assert row["body_html"] == ""
        assert row["has_attachments"] == 0
        print("\n  _extract_email_row(headers_only=True) -> content_level=0, empty body")

    async def test_extract_email_row_full(self):
        """Unit-level check: _extract_email_row with headers_only=False sets content_level=1."""
        from unittest.mock import MagicMock

        from external_data_ingestion.email.sync import _extract_email_row

        msg = MagicMock()
        msg.from_values = MagicMock(email="a@b.com", name="A", full="A <a@b.com>")
        msg.to_values = []
        msg.cc_values = []
        msg.headers = {"message-id": ("<test2@id>",)}
        msg.date = MagicMock(year=2025, isoformat=lambda: "2025-01-01T00:00:00")
        msg.subject = "Test"
        msg.text = "Body text"
        msg.html = "<p>HTML</p>"
        msg.flags = ()
        msg.size_rfc822 = 1000
        msg.size = 1000
        msg.attachments = [MagicMock()]
        msg.uid = "43"
        msg.obj = None

        row = _extract_email_row(msg, "test@x.com", "INBOX", headers_only=False)
        assert row["content_level"] == 1
        assert row["body_plain"] == "Body text"
        assert row["body_html"] == "<p>HTML</p>"
        assert row["has_attachments"] == 1
        print("  _extract_email_row(headers_only=False) -> content_level=1, body populated")


class TestBodyUpgrade:
    """Verify body upgrade from content_level=0 to content_level=1."""

    async def test_upgrade_folder_bodies(self, account, db, attachments_dir):
        """Downgrade a synced email to content_level=0, then call upgrade to restore it."""
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import upgrade_folder_bodies

        async with db.execute(
            "SELECT id, uid, body_plain FROM emails "
            "WHERE account_email = ? AND mailbox = 'INBOX' AND content_level = 1 LIMIT 1",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No content_level=1 emails to test upgrade with")

        original_body = row["body_plain"]
        email_id = row["id"]
        email_uid = row["uid"]

        await db.execute(
            "UPDATE emails SET body_plain = '', body_html = '', content_level = 0 WHERE id = ?",
            (email_id,),
        )
        await db.commit()

        provider = get_provider(account)
        async with provider.connection() as mb:
            upgraded = await upgrade_folder_bodies(
                account, "INBOX", db, attachments_dir, since_days=36500, mb=mb,
            )
        assert upgraded >= 1, "Should have upgraded at least one message"

        async with db.execute(
            "SELECT content_level, body_plain FROM emails WHERE id = ?", (email_id,)
        ) as cur:
            updated = await cur.fetchone()

        assert updated["content_level"] == 1, "content_level should be 1 after upgrade"
        assert len(updated["body_plain"]) > 0 or original_body == "", (
            "body_plain should be restored after upgrade"
        )
        print(f"\n  upgrade_folder_bodies: uid={email_uid} restored to content_level=1")


class TestLazyBodyFetch:
    """Verify that EmailClient.get_email() lazy-fetches body for content_level=0 rows."""

    async def test_lazy_fetch_upgrades_content_level(self, client, account, db):
        """Downgrade a synced email to content_level=0, then call get_email() to trigger lazy fetch."""
        async with db.execute(
            "SELECT id, message_id, body_plain FROM emails "
            "WHERE account_email = ? AND mailbox = 'INBOX' AND content_level = 1 "
            "AND body_plain != '' LIMIT 1",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            pytest.skip("No emails with body to test lazy fetch")

        email_id = row["id"]
        message_id = row["message_id"]

        await db.execute(
            "UPDATE emails SET body_plain = '', body_html = '', content_level = 0 WHERE id = ?",
            (email_id,),
        )
        await db.commit()

        email_obj = await client.get_email(message_id)
        assert email_obj is not None
        assert email_obj.content_level == 1, "Lazy fetch should upgrade content_level to 1"
        print(f"\n  Lazy body fetch: {message_id} upgraded to content_level=1")

        async with db.execute(
            "SELECT content_level FROM emails WHERE id = ?", (email_id,)
        ) as cur:
            db_row = await cur.fetchone()
        assert db_row["content_level"] == 1, "DB should reflect the upgrade"


class TestMetadataOnlyAttachments:
    """Verify _store_attachments metadata_only mode."""

    async def test_store_attachments_metadata_only(self, db):
        """Insert a fake email, then store attachments metadata-only."""
        from unittest.mock import MagicMock

        from external_data_ingestion.email.sync import _store_attachments

        await db.execute(
            """INSERT INTO emails
               (uid, message_id, account_email, mailbox, subject,
                to_recipients, cc_recipients, flags, content_level)
               VALUES (99999, '<metadata-test@test>', 'test@meta.local',
                       'INBOX', 'Metadata test', '[]', '[]', '[]', 1)""",
        )
        await db.commit()

        async with db.execute(
            "SELECT id FROM emails WHERE message_id = '<metadata-test@test>'"
        ) as cur:
            email_id = (await cur.fetchone())[0]

        att = MagicMock()
        att.filename = "report.pdf"
        att.content_type = "application/pdf"
        att.payload = b"fake-payload-bytes"
        att.content_id = ""
        att.content_disposition = "attachment"

        msg = MagicMock()
        msg.attachments = [att]

        await _store_attachments(db, email_id, msg, "/tmp/att", metadata_only=True)
        await db.commit()

        async with db.execute(
            "SELECT filename, size_bytes, content_blob, storage_path "
            "FROM attachments WHERE email_id = ?",
            (email_id,),
        ) as cur:
            row = await cur.fetchone()

        assert row is not None
        assert row["filename"] == "report.pdf"
        assert row["size_bytes"] == len(b"fake-payload-bytes")
        assert row["content_blob"] is None, "metadata_only should not store content_blob"
        assert row["storage_path"] is None, "metadata_only should not store storage_path"
        print("\n  _store_attachments(metadata_only=True): metadata stored, no payload")

        await db.execute("DELETE FROM emails WHERE message_id = '<metadata-test@test>'")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
#  20. Full-round summary
# ═══════════════════════════════════════════════════════════════════


class TestSummary:

    async def test_event_log_summary(self, db):
        """Print a summary of all events generated during the test run."""
        async with db.execute(
            "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type ORDER BY cnt DESC"
        ) as cur:
            rows = await cur.fetchall()

        print("\n  ── Event log summary ──")
        total = 0
        for r in rows:
            print(f"    {r['event_type']:20s}  {r['cnt']}")
            total += r["cnt"]
        print(f"    {'TOTAL':20s}  {total}")

    async def test_email_count_summary(self, db, email_address):
        async with db.execute(
            "SELECT mailbox, COUNT(*) as cnt FROM emails "
            "WHERE account_email = ? GROUP BY mailbox ORDER BY cnt DESC",
            (email_address,),
        ) as cur:
            rows = await cur.fetchall()

        print("\n  ── Email count by mailbox ──")
        for r in rows:
            print(f"    {r['mailbox']:30s}  {r['cnt']}")
