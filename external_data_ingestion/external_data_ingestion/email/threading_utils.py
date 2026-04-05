"""Thread reconstruction from In-Reply-To / References headers."""

from __future__ import annotations

import aiosqlite


async def get_thread(
    db: aiosqlite.Connection,
    message_id: str,
) -> list[dict]:
    """Reconstruct a thread containing the given *message_id*.

    Strategy:
    1. Load the target email's ``references_hdr`` which contains the full
       chain of Message-IDs from the thread root forward.
    2. Collect all Message-IDs in the chain (references + in_reply_to + self).
    3. Query the DB for all emails whose ``message_id`` is in that set.
    4. Sort by date ascending to present the thread chronologically.
    """
    async with db.execute(
        "SELECT message_id, in_reply_to, references_hdr FROM emails WHERE message_id = ?",
        (message_id,),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return []

    thread_ids: set[str] = {message_id}

    refs_raw = row["references_hdr"] or ""
    for ref in refs_raw.split():
        ref = ref.strip()
        if ref:
            thread_ids.add(ref)

    in_reply_to = (row["in_reply_to"] or "").strip()
    if in_reply_to:
        thread_ids.add(in_reply_to)

    thread_ids = await _expand_thread(db, thread_ids)

    placeholders = ", ".join("?" for _ in thread_ids)
    query = f"""
        SELECT id, uid, message_id, account_email, mailbox, subject,
               sender_raw, sender_name, sender_email, sender_domain,
               to_recipients, cc_recipients, date, body_plain, body_html,
               flags, size_bytes, has_attachments, in_reply_to, references_hdr,
               synced_at
        FROM emails
        WHERE message_id IN ({placeholders})
        ORDER BY date ASC
    """
    async with db.execute(query, tuple(thread_ids)) as cur:
        rows = await cur.fetchall()

    return [dict(r) for r in rows]


async def _expand_thread(
    db: aiosqlite.Connection,
    seed_ids: set[str],
) -> set[str]:
    """Walk references bidirectionally to capture the full thread.

    Handles cases where the initial email only has a partial reference chain
    (e.g., a reply-to-reply where the middle message was fetched first).
    """
    seen = set(seed_ids)
    frontier = set(seed_ids)

    for _ in range(20):
        if not frontier:
            break

        placeholders = ", ".join("?" for _ in frontier)

        query = f"""
            SELECT message_id, in_reply_to, references_hdr FROM emails
            WHERE message_id IN ({placeholders})
               OR in_reply_to IN ({placeholders})
        """
        params = tuple(frontier) + tuple(frontier)

        new_ids: set[str] = set()
        async with db.execute(query, params) as cur:
            async for row in cur:
                for field in ("message_id", "in_reply_to"):
                    val = (row[field] or "").strip()
                    if val and val not in seen:
                        new_ids.add(val)
                for ref in (row["references_hdr"] or "").split():
                    ref = ref.strip()
                    if ref and ref not in seen:
                        new_ids.add(ref)

        seen.update(new_ids)
        frontier = new_ids

    return seen
