"""Tests for the Gmail-ish query parser and real-DB integration via EmailClient.

Unit tests (TestParseEmailQuery, TestBuildSearchSql) need no DB.
Integration tests (TestClientSearch) use EmailClient.create() to connect to
the daemon's real SQLite DB, discover active accounts, and run queries against
synced data.

Run:
    uv run pytest external_data_ingestion/tests/test_query_parser.py -v -s
"""

from __future__ import annotations

import asyncio

import pytest

from external_data_ingestion.email.query_parser import (
    ParsedEmailQuery,
    build_search_sql,
    parse_email_query,
)


# ═══════════════════════════════════════════════════════════════════
#  1. parse_email_query — pure unit tests
# ═══════════════════════════════════════════════════════════════════


class TestParseEmailQuery:

    def test_bare_words(self):
        p = parse_email_query("invoice march")
        assert p.fts_terms == ["invoice", "march"]
        assert not p.sender_filters
        assert not p.subject_terms

    def test_from_with_email(self):
        p = parse_email_query("from:alice@example.com")
        assert p.sender_filters == ["alice@example.com"]
        assert not p.fts_terms

    def test_from_with_name(self):
        p = parse_email_query("from:alice")
        assert p.sender_filters == ["alice"]

    def test_to_operator(self):
        p = parse_email_query("to:bob@test.com")
        assert p.to_filters == ["bob@test.com"]

    def test_subject_operator(self):
        p = parse_email_query("subject:invoice")
        assert p.subject_terms == ["invoice"]
        assert not p.fts_terms

    def test_in_inbox(self):
        p = parse_email_query("in:inbox")
        assert p.mailbox == "INBOX"

    def test_in_sent(self):
        p = parse_email_query("in:sent")
        assert p.mailbox == "Sent"

    def test_in_spam_maps_to_junk(self):
        p = parse_email_query("in:spam")
        assert p.mailbox == "Junk"

    def test_has_attachment(self):
        p = parse_email_query("has:attachment")
        assert p.has_attachment is True

    def test_is_unread(self):
        p = parse_email_query("is:unread")
        assert p.is_read is False

    def test_is_read(self):
        p = parse_email_query("is:read")
        assert p.is_read is True

    def test_after_date(self):
        p = parse_email_query("after:2024-01-15")
        assert p.date_after == "2024-01-15"

    def test_before_date(self):
        p = parse_email_query("before:2024-06-01")
        assert p.date_before == "2024-06-01"

    def test_mixed_operators_and_bare_words(self):
        p = parse_email_query("from:alice@test.com subject:invoice quarterly report")
        assert p.sender_filters == ["alice@test.com"]
        assert p.subject_terms == ["invoice"]
        assert p.fts_terms == ["quarterly", "report"]

    def test_multiple_from_operators(self):
        p = parse_email_query("from:alice from:bob")
        assert p.sender_filters == ["alice", "bob"]

    def test_quoted_subject_value(self):
        p = parse_email_query('subject:"monthly report"')
        assert p.subject_terms == ["monthly report"]

    def test_full_complex_query(self):
        p = parse_email_query(
            'from:alice@test.com subject:"Q1 report" in:inbox '
            "has:attachment after:2024-01-01 before:2024-04-01 budget"
        )
        assert p.sender_filters == ["alice@test.com"]
        assert p.subject_terms == ["Q1 report"]
        assert p.mailbox == "INBOX"
        assert p.has_attachment is True
        assert p.date_after == "2024-01-01"
        assert p.date_before == "2024-04-01"
        assert p.fts_terms == ["budget"]

    def test_case_insensitive_operators(self):
        p = parse_email_query("FROM:alice SUBJECT:test IN:Inbox")
        assert p.sender_filters == ["alice"]
        assert p.subject_terms == ["test"]
        assert p.mailbox == "INBOX"

    def test_empty_query(self):
        p = parse_email_query("")
        assert p == ParsedEmailQuery()

    def test_only_whitespace(self):
        p = parse_email_query("   ")
        assert p == ParsedEmailQuery()


# ═══════════════════════════════════════════════════════════════════
#  2. build_search_sql — SQL generation unit tests
# ═══════════════════════════════════════════════════════════════════


class TestBuildSearchSql:

    def test_bare_words_produce_fts_match(self):
        parsed = parse_email_query("invoice march")
        sql, params = build_search_sql(parsed)
        assert "emails_fts MATCH ?" in sql
        assert '"invoice" AND "march"' == params[0]

    def test_from_email_produces_exact_filter(self):
        parsed = parse_email_query("from:alice@test.com")
        sql, params = build_search_sql(parsed)
        assert "emails_fts" not in sql
        assert "sender_email = ?" in sql
        assert "alice@test.com" in params

    def test_from_name_produces_like_filter(self):
        parsed = parse_email_query("from:alice")
        sql, params = build_search_sql(parsed)
        assert "sender_email LIKE ?" in sql
        assert "sender_name LIKE ?" in sql
        assert "%alice%" in params

    def test_subject_uses_fts_column_prefix(self):
        parsed = parse_email_query("subject:invoice")
        sql, params = build_search_sql(parsed)
        assert "emails_fts MATCH ?" in sql
        assert params[0] == 'subject:"invoice"'

    def test_has_attachment_filter(self):
        parsed = parse_email_query("has:attachment")
        sql, params = build_search_sql(parsed)
        assert "has_attachments = 1" in sql

    def test_is_unread_filter(self):
        parsed = parse_email_query("is:unread")
        sql, params = build_search_sql(parsed)
        assert "flags NOT LIKE ?" in sql

    def test_date_filters(self):
        parsed = parse_email_query("after:2024-01-01 before:2024-06-01")
        sql, params = build_search_sql(parsed)
        assert "date >= ?" in sql
        assert "date < ?" in sql
        assert "2024-01-01" in params
        assert "2024-06-01" in params

    def test_account_email_filter(self):
        parsed = parse_email_query("invoice")
        sql, params = build_search_sql(parsed, account_email="me@test.com")
        assert "account_email = ?" in sql
        assert "me@test.com" in params

    def test_mailbox_filter(self):
        parsed = parse_email_query("in:inbox")
        sql, params = build_search_sql(parsed)
        assert "mailbox = ?" in sql
        assert "INBOX" in params

    def test_limit_always_present(self):
        parsed = parse_email_query("test")
        sql, params = build_search_sql(parsed, limit=25)
        assert sql.endswith("LIMIT ?")
        assert params[-1] == 25

    def test_mixed_fts_and_structured(self):
        parsed = parse_email_query("from:alice@test.com subject:invoice quarterly")
        sql, params = build_search_sql(parsed, account_email="me@test.com")
        assert "emails_fts MATCH ?" in sql
        assert "sender_email = ?" in sql
        assert "account_email = ?" in sql
        fts_match = params[0]
        assert 'subject:"invoice"' in fts_match
        assert '"quarterly"' in fts_match

    def test_no_fts_when_only_structured_filters(self):
        parsed = parse_email_query("from:alice@test.com has:attachment in:inbox")
        sql, params = build_search_sql(parsed)
        assert "emails_fts" not in sql
        assert "SELECT * FROM emails" in sql

    def test_special_chars_escaped_in_fts(self):
        parsed = parse_email_query('user@domain.com')
        sql, params = build_search_sql(parsed)
        assert "emails_fts MATCH ?" in sql
        assert '"user@domain.com"' == params[0]

    def test_to_filter(self):
        parsed = parse_email_query("to:bob@test.com")
        sql, params = build_search_sql(parsed)
        assert "to_recipients LIKE ?" in sql
        assert "%bob@test.com%" in params


# ═══════════════════════════════════════════════════════════════════
#  3. Integration — real EmailClient against daemon's SQLite DB
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def client_and_account(event_loop):
    """Create a real EmailClient connected to the daemon DB.

    Discovers active accounts and yields (client, first_account_email).
    Skips the entire module if no active accounts are configured.
    """
    from external_data_ingestion.email.client import EmailClient

    async def _setup():
        client = await EmailClient.create()
        accounts = await client.get_active_accounts()
        if not accounts:
            await client.close()
            return None, None
        return client, accounts[0].email

    client, account_email = event_loop.run_until_complete(_setup())
    if client is None:
        pytest.skip("No active email accounts configured — skipping integration tests")

    yield client, account_email

    event_loop.run_until_complete(client.close())


class TestClientSearch:
    """Run Gmail-style queries through the real EmailClient.search().

    These hit the daemon's SQLite DB with real synced data, so results
    are non-deterministic — we only assert structural correctness (no
    crashes, correct return types, filters narrow results).
    """

    def _run(self, event_loop, coro):
        return event_loop.run_until_complete(coro)

    def test_bare_word_search(self, event_loop, client_and_account):
        client, account = client_and_account
        results = self._run(event_loop, client.search("hello", account_email=account))
        assert isinstance(results, list)
        for e in results:
            assert hasattr(e, "message_id")

    def test_from_with_email_address(self, event_loop, client_and_account):
        """from:user@domain.com should not crash (previously caused FTS error)."""
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search(f"from:{account}", account_email=account),
        )
        assert isinstance(results, list)

    def test_subject_operator(self, event_loop, client_and_account):
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search("subject:test", account_email=account),
        )
        assert isinstance(results, list)

    def test_in_inbox(self, event_loop, client_and_account):
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search("in:inbox", account_email=account, limit=5),
        )
        assert isinstance(results, list)
        for e in results:
            assert e.mailbox == "INBOX"

    def test_has_attachment(self, event_loop, client_and_account):
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search("has:attachment", account_email=account, limit=5),
        )
        assert isinstance(results, list)
        for e in results:
            assert e.has_attachments is True

    def test_date_filter(self, event_loop, client_and_account):
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search("after:2024-01-01", account_email=account, limit=5),
        )
        assert isinstance(results, list)
        for e in results:
            assert e.date >= "2024-01-01"

    def test_combined_gmail_style_query(self, event_loop, client_and_account):
        """The exact kind of query Jarvis would produce."""
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search(
                f"from:{account} subject:test in:inbox",
                account_email=account,
                limit=5,
            ),
        )
        assert isinstance(results, list)
        for e in results:
            assert e.mailbox == "INBOX"

    def test_is_unread(self, event_loop, client_and_account):
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search("is:unread", account_email=account, limit=5),
        )
        assert isinstance(results, list)
        for e in results:
            assert "\\Seen" not in e.flags

    def test_email_address_as_bare_word(self, event_loop, client_and_account):
        """Raw email addresses used to crash with FTS syntax error."""
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search(account, account_email=account, limit=3),
        )
        assert isinstance(results, list)

    def test_empty_query_returns_all(self, event_loop, client_and_account):
        """Empty string should not crash — returns recent emails."""
        client, account = client_and_account
        results = self._run(
            event_loop,
            client.search("", account_email=account, limit=3),
        )
        assert isinstance(results, list)
