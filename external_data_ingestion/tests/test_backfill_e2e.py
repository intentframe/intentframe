"""End-to-end test for the priority-first sync + backfill flow.

Exercises every phase exactly as the daemon would, on a fresh DB,
then verifies that every folder (except All Mail) is fully synced
with no gaps.

Requires a real email account.  Provide credentials via:
  - external_data_ingestion/tests/test_e2e_config.yaml   (default)
  - CLI: --email / --password

Run:
    uv run pytest external_data_ingestion/tests/test_backfill_e2e.py -v -s
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio  # noqa: F401 — needed for the fresh_db fixture
import yaml

BODY_SYNC_DAYS = 90
_E2E_CONFIG_PATH = Path(__file__).parent / "test_e2e_config.yaml"


def _load_e2e_test_config() -> dict[str, str]:
    """Read email/password from the E2E YAML file next to this test."""
    if not _E2E_CONFIG_PATH.exists():
        return {}
    raw = yaml.safe_load(_E2E_CONFIG_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


@pytest.fixture(scope="session")
def email_address(request: Any) -> str:
    """Override shared credentials for this module only."""
    addr = request.config.getoption("--email") or _load_e2e_test_config().get("email")
    if not addr:
        pytest.skip(
            "No E2E test email configured. "
            "Copy test_e2e_config_example.yaml → test_e2e_config.yaml and fill in your email, "
            "or pass --email <address>."
        )
    return addr


@pytest.fixture(scope="session")
def email_password(request: Any) -> str:
    """Override shared credentials for this module only."""
    pw = request.config.getoption("--password") or _load_e2e_test_config().get("password")
    if not pw:
        pytest.skip(
            "No E2E test password configured. "
            "Add 'password: <app-password>' to test_e2e_config.yaml, "
            "or pass --password <app-password>."
        )
    return pw


@pytest_asyncio.fixture(scope="session")
async def fresh_db(service_config):
    """A brand-new DB with zero prior sync state."""
    from external_data_ingestion.email.db import init_db

    db_path = service_config.db_path.parent / "backfill_e2e.db"
    conn = await init_db(db_path)
    yield conn
    await conn.close()


async def _query_one(db, sql, params=()):
    async with db.execute(sql, params) as cur:
        return (await cur.fetchone())[0]


async def _query_all(db, sql, params=()):
    async with db.execute(sql, params) as cur:
        return await cur.fetchall()


async def _folder_counts(db, email):
    """Return {mailbox: (total, content_level_1)} for every folder in the DB."""
    rows = await _query_all(
        db,
        """SELECT mailbox,
                  COUNT(*) AS total,
                  SUM(CASE WHEN content_level = 1 THEN 1 ELSE 0 END) AS cl1
           FROM emails WHERE account_email = ?
           GROUP BY mailbox""",
        (email,),
    )
    return {r[0]: (r[1], r[2]) for r in rows}


class TestBackfillE2E:
    """Runs the full sync flow phase-by-phase on a fresh DB."""

    async def test_00_db_is_empty(self, fresh_db, account):
        """Precondition: fresh DB has zero emails and zero sync state."""
        email_count = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM emails WHERE account_email = ?",
            (account.email,),
        )
        sync_count = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM sync_state WHERE account_email = ?",
            (account.email,),
        )
        assert email_count == 0
        assert sync_count == 0
        print("\n  Phase 0: DB is empty ✓")

    # ── Phase 1: Priority pass ──────────────────────────────────────

    async def test_01_priority_pass(self, fresh_db, account, attachments_dir, discovered_folders):
        """INBOX + Sent full content for the last BODY_SYNC_DAYS days."""
        from external_data_ingestion.email.folders import folder_for_role
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)
        results: dict[str, int] = {}
        async with provider.connection() as mb:
            for role in ("inbox", "sent"):
                name = folder_for_role(discovered_folders, role)
                if not name:
                    continue
                count = await sync_folder(
                    account, name, fresh_db, attachments_dir,
                    since_days=BODY_SYNC_DAYS, mb=mb,
                )
                results[name] = count

        assert len(results) > 0, "Should sync at least one priority folder"
        total = sum(results.values())
        print(f"\n  Phase 1 (priority pass): {results}  total={total}")

    async def test_02_after_priority_inbox_has_bodies(self, fresh_db, account):
        """INBOX rows from the priority pass should all have content_level=1."""
        total = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = 'INBOX'",
            (account.email,),
        )
        cl1 = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = 'INBOX' AND content_level = 1",
            (account.email,),
        )
        assert total > 0, "Priority pass should have synced INBOX messages"
        assert cl1 == total, f"All {total} INBOX rows should be content_level=1, got {cl1}"
        print(f"  Phase 1 check: INBOX {total} emails, all content_level=1 ✓")

    async def test_03_after_priority_only_inbox_sent(self, fresh_db, account, discovered_folders):
        """After phase 1 the DB should only contain INBOX and/or Sent folders."""
        from external_data_ingestion.email.folders import folder_for_role

        rows = await _query_all(
            fresh_db,
            "SELECT DISTINCT mailbox FROM emails WHERE account_email = ?",
            (account.email,),
        )
        mailboxes = {r[0] for r in rows}
        allowed = {"INBOX"}

        sent_name = folder_for_role(discovered_folders, "sent")
        if sent_name:
            allowed.add(sent_name)

        assert mailboxes <= allowed, (
            f"After priority pass only {allowed} expected, got {mailboxes}"
        )
        print(f"  Phase 1 check: only priority folders present {mailboxes} ✓")

    # ── Phase 2: Backfill step 1 — old INBOX + Sent headers ────────

    async def test_04_backfill_old_headers(self, fresh_db, account, attachments_dir, discovered_folders):
        """full=True headers-only for INBOX + Sent fills in >90-day messages."""
        from external_data_ingestion.email.folders import folder_for_role
        from external_data_ingestion.email.imap_connection import get_provider
        from external_data_ingestion.email.sync import sync_folder

        provider = get_provider(account)

        before_inbox = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = 'INBOX'",
            (account.email,),
        )

        async with provider.connection() as mb:
            await sync_folder(
                account, "INBOX", fresh_db, attachments_dir,
                full=True, headers_only=True, mb=mb,
            )

        sent_name = folder_for_role(discovered_folders, "sent")
        if sent_name:
            before_sent = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ?",
                (account.email, sent_name),
            )
            async with provider.connection() as mb:
                await sync_folder(
                    account, sent_name, fresh_db, attachments_dir,
                    full=True, headers_only=True, mb=mb,
                )
            after_sent = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ?",
                (account.email, sent_name),
            )
            cl1_sent = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ? AND content_level = 1",
                (account.email, sent_name),
            )
            print(f"  Phase 2.1: Sent old headers backfilled +{after_sent - before_sent} (total {after_sent}), {cl1_sent} still have bodies")

        after_inbox = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = 'INBOX'",
            (account.email,),
        )
        cl1_inbox = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = 'INBOX' AND content_level = 1",
            (account.email,),
        )
        assert after_inbox >= before_inbox, "Should not lose any rows"
        assert cl1_inbox > 0, "Priority-pass rows must still be content_level=1 (INSERT OR IGNORE preserves them)"

        new_headers = after_inbox - before_inbox
        print(f"  Phase 2.1: INBOX old headers backfilled +{new_headers} (total {after_inbox}), {cl1_inbox} still have bodies ✓")

    # ── Phase 2: Backfill step 2 — headers for all other folders ───

    async def test_05_backfill_other_headers(self, fresh_db, account, attachments_dir):
        """Headers-only for all folders except All Mail, INBOX, Sent."""
        from external_data_ingestion.email.sync import sync_all_folders

        await sync_all_folders(
            account, fresh_db, attachments_dir,
            headers_only=True, skip_roles={"all", "inbox", "sent"},
        )

        rows = await _query_all(
            fresh_db,
            "SELECT DISTINCT mailbox FROM emails WHERE account_email = ?",
            (account.email,),
        )
        mailboxes = {r[0] for r in rows}
        print(f"  Phase 2.2: folders now in DB = {mailboxes}")

    # ── Phase 2: Backfill step 3 — 90d bodies for other folders ────

    async def test_06_backfill_other_bodies(self, fresh_db, account, attachments_dir):
        """Upgrade bodies for the recent window in non-priority folders."""
        from external_data_ingestion.email.sync import upgrade_all_folders_bodies

        upgraded = await upgrade_all_folders_bodies(
            account, fresh_db, attachments_dir,
            since_days=BODY_SYNC_DAYS, skip_roles={"all", "inbox", "sent"},
        )
        print(f"  Phase 2.3: upgraded {upgraded} bodies in non-priority folders ✓")

    # ── Final validation ───────────────────────────────────────────

    async def test_07_no_all_mail_in_db(self, fresh_db, account, discovered_folders):
        """All Mail must never appear in the DB."""
        from external_data_ingestion.email.folders import folder_for_role

        all_mail_name = folder_for_role(discovered_folders, "all")
        if all_mail_name:
            count = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ?",
                (account.email, all_mail_name),
            )
            assert count == 0, f"All Mail ({all_mail_name}) should have 0 rows, got {count}"
            print(f"  All Mail ({all_mail_name}) correctly excluded: 0 rows ✓")
        else:
            print("  No All Mail folder detected (non-Gmail?), skip ✓")

    async def test_08_every_selectable_folder_synced(self, fresh_db, account, discovered_folders):
        """Every selectable folder (except All Mail) must have sync_state."""
        selectable = [
            f for f in discovered_folders
            if f.get("selectable", True) and f.get("role") != "all"
        ]

        db_mailboxes = {
            r[0] for r in await _query_all(
                fresh_db,
                "SELECT DISTINCT mailbox FROM emails WHERE account_email = ?",
                (account.email,),
            )
        }
        synced_in_state = {
            r[0] for r in await _query_all(
                fresh_db,
                "SELECT mailbox FROM sync_state WHERE account_email = ?",
                (account.email,),
            )
        }

        expected_names = {f["name"] for f in selectable}
        missing_from_state = expected_names - synced_in_state
        assert not missing_from_state, (
            f"Folders never synced (no sync_state row): {missing_from_state}"
        )

        empty_folders = expected_names - db_mailboxes
        if empty_folders:
            print(f"  Note: folders synced but have 0 messages (normal for empty folders): {empty_folders}")

        print(f"  All {len(expected_names)} selectable folders (excl All Mail) have sync_state ✓")

    async def test_09_priority_folders_have_full_bodies(self, fresh_db, account, discovered_folders):
        """INBOX and Sent: every message within the 90d window must have content_level=1."""
        from external_data_ingestion.email.folders import folder_for_role

        cutoff = (datetime.now(UTC) - timedelta(days=BODY_SYNC_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        for role in ("inbox", "sent"):
            name = folder_for_role(discovered_folders, role)
            if not name:
                continue

            total_recent = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ? AND date >= ?",
                (account.email, name, cutoff),
            )
            cl1_recent = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM emails WHERE account_email = ? AND mailbox = ? AND date >= ? AND content_level = 1",
                (account.email, name, cutoff),
            )
            assert cl1_recent == total_recent, (
                f"{name}: {total_recent} recent messages but only {cl1_recent} have bodies"
            )
            print(f"  {name}: {total_recent} recent messages, all have bodies ✓")

    async def test_09b_body_content_not_empty(self, fresh_db, account):
        """content_level=1 rows must actually contain body text, not just the flag."""
        rows = await _query_all(
            fresh_db,
            """SELECT mailbox, uid, body_plain, body_html FROM emails
               WHERE account_email = ? AND content_level = 1
               ORDER BY RANDOM() LIMIT 20""",
            (account.email,),
        )
        assert len(rows) > 0, "Should have content_level=1 rows to check"

        empty = []
        for r in rows:
            if not r["body_plain"] and not r["body_html"]:
                empty.append((r["mailbox"], r["uid"]))

        assert not empty, (
            f"{len(empty)} content_level=1 rows have empty body_plain AND body_html: "
            f"{empty[:5]}"
        )
        print(f"  Sampled {len(rows)} content_level=1 rows — all have body content ✓")

    async def test_09c_attachment_metadata(self, fresh_db, account):
        """Emails with has_attachments=1 must have matching rows in the attachments table."""
        emails_with_att = await _query_all(
            fresh_db,
            """SELECT id, mailbox, uid FROM emails
               WHERE account_email = ? AND has_attachments = 1""",
            (account.email,),
        )

        if not emails_with_att:
            print("  No emails with attachments in this account — skip ✓")
            return

        missing = []
        for row in emails_with_att:
            att_count = await _query_one(
                fresh_db,
                "SELECT COUNT(*) FROM attachments WHERE email_id = ?",
                (row["id"],),
            )
            if att_count == 0:
                missing.append((row["mailbox"], row["uid"]))

        assert not missing, (
            f"{len(missing)} emails have has_attachments=1 but no attachment rows: "
            f"{missing[:5]}"
        )

        bad_metadata = await _query_all(
            fresh_db,
            """SELECT a.id, a.filename, a.size_bytes, a.content_type, a.is_inline
               FROM attachments a
               JOIN emails e ON e.id = a.email_id
               WHERE e.account_email = ? AND (a.filename = '' OR a.size_bytes <= 0)""",
            (account.email,),
        )
        if bad_metadata:
            inline_count = sum(1 for r in bad_metadata if r["is_inline"])
            non_inline = [r for r in bad_metadata if not r["is_inline"]]
            types = {}
            for r in non_inline:
                ct = r["content_type"] or "unknown"
                types[ct] = types.get(ct, 0) + 1
            print(f"  Note: {len(bad_metadata)} attachment rows with empty filename or zero size "
                  f"({inline_count} inline, {len(non_inline)} non-inline)")
            if types:
                print(f"    Non-inline content types: {types}")
        print(f"  {len(emails_with_att)} emails with attachments — all have attachment rows ✓")

    async def test_09d_attachment_download(self, fresh_db, account):
        """Pick a real attachment and verify IMAP fetch returns bytes."""
        from imap_tools import AND
        from external_data_ingestion.email.imap_connection import get_provider

        row = None
        async with fresh_db.execute(
            """SELECT e.mailbox, e.uid, a.filename
               FROM attachments a
               JOIN emails e ON e.id = a.email_id
               WHERE e.account_email = ? AND a.filename != ''
               LIMIT 1""",
            (account.email,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            print("  No attachments to download in this account — skip ✓")
            return

        mailbox = row["mailbox"]
        uid = row["uid"]
        filename = row["filename"]

        provider = get_provider(account)
        async with provider.connection() as mb:
            def _fetch_attachment():
                mb.folder.set(mailbox, readonly=True)
                msgs = list(mb.fetch(AND(uid=str(uid)), mark_seen=False))
                if not msgs:
                    return None
                for att in msgs[0].attachments:
                    if att.filename == filename:
                        return att.payload
                return None
            data = await asyncio.to_thread(_fetch_attachment)
        assert data is not None, f"IMAP returned no payload for '{filename}' (uid={uid})"
        assert len(data) > 0, f"IMAP returned empty bytes for '{filename}' (uid={uid})"
        print(f"  Downloaded '{filename}' ({len(data)} bytes) from uid={uid} in {mailbox} ✓")

    # ── IMAP server integrity check ──────────────────────────────────

    async def test_10_imap_uid_integrity(self, fresh_db, account):
        """Use the production verify_integrity() to confirm every server UID is in the local DB."""
        from external_data_ingestion.email.sync import verify_integrity

        result = await verify_integrity(account, fresh_db, skip_roles={"all"})

        print(f"\n  {'Folder':<35s} {'Server':>7s} {'Local':>7s} {'Missing':>8s} {'XFolder':>8s}")
        print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 8} {'─' * 8}")
        for name, info in sorted(result["folders"].items()):
            cf = info.get("cross_folder", 0)
            flag = "✓" if not info["missing"] else "✗"
            print(
                f"  {name:<35s} {info['server']:>7d} {info['local']:>7d} "
                f"{len(info['missing']):>7d} {cf:>8d}  {flag}"
            )
        print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 8} {'─' * 8}")
        print(
            f"  {'TOTAL':<35s} {result['total_server']:>7d} "
            f"{result['total_local']:>7d}"
        )

        gaps = {
            name: info["missing"]
            for name, info in result["folders"].items()
            if info["missing"]
        }
        assert not gaps, (
            f"UIDs on server but missing from local DB:\n"
            + "\n".join(
                f"  {folder}: {len(uids)} missing (e.g. {uids[:5]})"
                for folder, uids in sorted(gaps.items())
            )
        )
        total_cf = sum(info.get("cross_folder", 0) for info in result["folders"].values())
        print(f"\n  UID integrity check passed — all {result['total_server']} server UIDs accounted for ({total_cf} cross-folder) ✓")

    # ── Summary ────────────────────────────────────────────────────

    async def test_11_summary(self, fresh_db, account):
        """Print a full summary of the DB state."""
        counts = await _folder_counts(fresh_db, account.email)

        print("\n  ── Backfill E2E Summary ──")
        print(f"  {'Folder':<35s} {'Total':>7s} {'Bodies':>7s} {'Headers-only':>13s}")
        print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 13}")
        grand_total = 0
        grand_cl1 = 0
        for mailbox, (total, cl1) in sorted(counts.items()):
            print(f"  {mailbox:<35s} {total:>7d} {cl1:>7d} {total - cl1:>13d}")
            grand_total += total
            grand_cl1 += cl1
        print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 13}")
        print(f"  {'TOTAL':<35s} {grand_total:>7d} {grand_cl1:>7d} {grand_total - grand_cl1:>13d}")

        sync_rows = await _query_one(
            fresh_db,
            "SELECT COUNT(*) FROM sync_state WHERE account_email = ?",
            (account.email,),
        )
        print(f"\n  sync_state rows: {sync_rows}")
        print(f"  Folders with data: {len(counts)}")
