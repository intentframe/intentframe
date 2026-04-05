"""Parse Gmail-style email search queries into structured SQL.

Translates operators like ``from:``, ``subject:``, ``has:attachment`` into
SQL WHERE clauses against the ``emails`` table and safe FTS5 MATCH terms
against ``emails_fts``.  Bare words become quoted FTS tokens so special
characters (``@``, ``.``) never reach the FTS parser raw.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPERATOR_RE = re.compile(
    r"""
    (?:^|\s)                       # start or whitespace
    (from|to|subject|in|has|is|after|before|newer_than|older_than|label)
    :                              # colon separator
    (?:"([^"]*)"                   # quoted value  …OR…
    |(\S+))                        # unquoted value
    """,
    re.VERBOSE | re.IGNORECASE,
)

_MAILBOX_ALIASES: dict[str, str] = {
    "inbox": "INBOX",
    "sent": "Sent",
    "drafts": "Drafts",
    "trash": "Trash",
    "junk": "Junk",
    "spam": "Junk",
    "archive": "Archive",
    "starred": "Flagged",
}


@dataclass
class ParsedEmailQuery:
    """Structured representation of a Gmail-ish search query."""

    fts_terms: list[str] = field(default_factory=list)
    subject_terms: list[str] = field(default_factory=list)
    sender_filters: list[str] = field(default_factory=list)
    to_filters: list[str] = field(default_factory=list)
    mailbox: str | None = None
    has_attachment: bool | None = None
    is_read: bool | None = None
    date_after: str | None = None
    date_before: str | None = None


def parse_email_query(raw: str) -> ParsedEmailQuery:
    """Parse a raw query string into a :class:`ParsedEmailQuery`."""
    parsed = ParsedEmailQuery()
    consumed_spans: list[tuple[int, int]] = []

    for m in _OPERATOR_RE.finditer(raw):
        op = m.group(1).lower()
        value = m.group(2) if m.group(2) is not None else m.group(3)
        consumed_spans.append((m.start(), m.end()))

        if op == "from":
            parsed.sender_filters.append(value)
        elif op == "to":
            parsed.to_filters.append(value)
        elif op == "subject":
            parsed.subject_terms.append(value)
        elif op in ("in", "label"):
            alias = value.lower()
            parsed.mailbox = _MAILBOX_ALIASES.get(alias, value)
        elif op == "has" and value.lower() in ("attachment", "attachments"):
            parsed.has_attachment = True
        elif op == "is":
            v = value.lower()
            if v == "unread":
                parsed.is_read = False
            elif v == "read":
                parsed.is_read = True
        elif op == "after":
            parsed.date_after = value
        elif op == "before":
            parsed.date_before = value

    remainder = _remove_spans(raw, consumed_spans).strip()
    if remainder:
        parsed.fts_terms = _tokenize_remainder(remainder)

    return parsed


def build_search_sql(
    parsed: ParsedEmailQuery,
    account_email: str | None = None,
    limit: int = 50,
) -> tuple[str, list]:
    """Compile a :class:`ParsedEmailQuery` into ``(sql, params)``."""
    conditions: list[str] = []
    params: list = []
    use_fts = bool(parsed.fts_terms or parsed.subject_terms)

    if use_fts:
        fts_parts: list[str] = []
        for term in parsed.subject_terms:
            fts_parts.append(f'subject:"{_fts_escape(term)}"')
        for term in parsed.fts_terms:
            fts_parts.append(f'"{_fts_escape(term)}"')
        fts_match = " AND ".join(fts_parts)

        base = (
            "SELECT emails.* FROM emails_fts "
            "JOIN emails ON emails.id = emails_fts.rowid "
            "WHERE emails_fts MATCH ?"
        )
        params.append(fts_match)
    else:
        base = "SELECT * FROM emails WHERE 1=1"

    for sender in parsed.sender_filters:
        if "@" in sender:
            conditions.append("emails.sender_email = ?")
            params.append(sender.lower())
        else:
            conditions.append(
                "(emails.sender_email LIKE ? OR emails.sender_name LIKE ?)"
            )
            pattern = f"%{sender}%"
            params.extend([pattern, pattern])

    for to_val in parsed.to_filters:
        conditions.append("emails.to_recipients LIKE ?")
        params.append(f"%{to_val}%")

    if parsed.mailbox:
        conditions.append("emails.mailbox = ?")
        params.append(parsed.mailbox)

    if parsed.has_attachment is True:
        conditions.append("emails.has_attachments = 1")

    if parsed.is_read is True:
        conditions.append("emails.flags LIKE ?")
        params.append('%\\Seen%')
    elif parsed.is_read is False:
        conditions.append("emails.flags NOT LIKE ?")
        params.append('%\\Seen%')

    if parsed.date_after:
        conditions.append("emails.date >= ?")
        params.append(parsed.date_after)

    if parsed.date_before:
        conditions.append("emails.date < ?")
        params.append(parsed.date_before)

    if account_email:
        conditions.append("emails.account_email = ?")
        params.append(account_email)

    sql = base
    for cond in conditions:
        sql += f" AND {cond}"
    sql += " ORDER BY emails.date DESC LIMIT ?"
    params.append(limit)

    return sql, params


# ── Helpers ──────────────────────────────────────────────────────


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Remove consumed operator spans from the original text."""
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def _tokenize_remainder(text: str) -> list[str]:
    """Split remaining free text into individual search tokens."""
    tokens: list[str] = []
    for part in text.split():
        cleaned = part.strip()
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _fts_escape(term: str) -> str:
    """Escape double-quotes inside a term for FTS5 quoted strings."""
    return term.replace('"', '""')
