Good question. Let me lay this out clearly.

## What the current design does

Yes — right now every `message_id` is pinned to exactly **one folder**. The schema enforces it:

```54:54:external_data_ingestion/external_data_ingestion/email/db.py
    UNIQUE (account_email, message_id)
```

Whichever folder is synced first "wins." If INBOX syncs first and a message also lives in Important, Starred, and Sent on Gmail, the DB stores it once with `mailbox='INBOX'`. The other three folders never see it.

## Is this a good design?

**For storing and searching email content — yes, it's fine.** You don't want four copies of the same email body, headers, and attachments. That's wasteful.

**For accurately representing which folders a message belongs to — no, it's broken.** Here's what it breaks in practice:

1. **`list_folders` is incomplete** — it returns only folders that "won" at least one message. If all Important messages were already in INBOX, Important never shows up:

```72:77:external_data_ingestion/external_data_ingestion/email/client.py
            """SELECT DISTINCT mailbox FROM emails WHERE account_email = ?
               ORDER BY mailbox""",
            (account_email,),
        ) as cur:
            rows = await cur.fetchall()
        return [Folder(name=r["mailbox"]) for r in rows]
```

2. **`get_recent("Important")` returns almost nothing** — because 1,131 of 1,142 Important messages are stored as `mailbox='INBOX'`

3. **`get_unread_count("Starred")` returns 0** — all starred messages are stored under other mailbox names

4. **Lazy body fetch uses `mailbox` + `uid` to find the message on IMAP** — if a message is stored under INBOX but the user asks for it in Starred context, the `uid` is the INBOX uid, which wouldn't match the Starred folder's uid:

```368:369:external_data_ingestion/external_data_ingestion/email/client.py
                mb.folder.set(email.mailbox, readonly=True)
                msgs = list(mb.fetch(AND(uid=str(email.uid)), mark_seen=False))
```

5. **`verify_integrity()` reported false gaps** — resolved: the function now fetches Message-ID headers for candidate "missing" UIDs and cross-references against all local message_ids, distinguishing true gaps from cross-folder duplicates

## What other mail clients do

Most local email clients solve this with a **separate labels/folders junction table**. The email body is stored once, but the folder membership is a many-to-many relationship.

## The fix: add an `email_folders` junction table

```
emails table (store content once)
┌────┬────────────┬───────────────────┬─────────┐
│ id │ message_id │ account_email     │ body... │
└────┴────────────┴───────────────────┴─────────┘
     UNIQUE (account_email, message_id)

email_folders table (many-to-many: which folders contain this email)
┌──────────┬─────────┬─────┐
│ email_id │ mailbox │ uid │
└──────────┴─────────┴─────┘
     UNIQUE (email_id, mailbox)
```

Schema would look like:

```sql
CREATE TABLE IF NOT EXISTS email_folders (
    id        INTEGER PRIMARY KEY,
    email_id  INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    mailbox   TEXT NOT NULL,
    uid       INTEGER NOT NULL,
    UNIQUE (email_id, mailbox)
);

CREATE INDEX idx_email_folders_mailbox
    ON email_folders (mailbox, uid);
```

Then:

- **`emails`** keeps `UNIQUE(account_email, message_id)` — content stored once, the `mailbox` column either gets removed or becomes the "primary" folder
- **`email_folders`** tracks every folder a message belongs to, with the correct per-folder UID
- **`INSERT OR IGNORE` on `emails`** still deduplicates content, but after inserting (or finding the existing row), you also `INSERT OR IGNORE INTO email_folders` to record the additional folder membership
- **`list_folders`** queries `email_folders` instead of `emails.mailbox`
- **`get_recent("Important")`** joins through `email_folders` and returns all messages that have an Important entry
- **`get_unread_count("Starred")`** actually works
- **Lazy body fetch** uses `email_folders.uid` + `email_folders.mailbox` to find the right IMAP folder and UID
- **`verify_integrity()`** checks against `email_folders` per folder — no false gaps

## Impact of the change

**What changes:**
- `db.py` — new table + migration (schema_version 3 → 4, since v3 added the `folders` metadata table)
- `sync.py` — after `INSERT OR IGNORE INTO emails`, also insert into `email_folders` for the current folder
- `client.py` — queries that filter by `mailbox` join through `email_folders` instead
- `actions.py` — `move_email` updates `email_folders`, not `emails.mailbox`
- `verify_integrity()` — checks `email_folders` UIDs per folder

**What doesn't change:**
- Email body/header storage — still one row per message
- FTS search — still searches `emails` content
- Attachments — still linked to `emails.id`
- The sync engine's fetch logic — still does `INSERT OR IGNORE` on content

## Is it worth doing now?

It depends on what consumers of this data need. If the system is primarily used for:

- **Search and content retrieval by message_id** — current design is fine
- **Browsing by folder, showing folder counts, folder-aware UI** — you need the junction table

The 4 missing INBOX UIDs (duplicate `message_id`s within INBOX itself) are a separate, smaller issue — those are genuinely duplicate deliveries that `INSERT OR IGNORE` correctly deduplicates. That's the right behavior.

## Current mitigations (without junction table)

Two targeted fixes keep the current single-mailbox schema working:

1. **`verify_integrity()` cross-folder awareness** — when per-folder UID comparison finds "missing" UIDs, the function fetches their Message-ID headers from the server and checks whether those message_ids exist in the local DB under any mailbox. UIDs that are present under a different folder are reported as `cross_folder` (not a gap) rather than `missing`. Only truly absent messages trigger a failure.

2. **Inline attachment metadata** — the E2E test excludes inline attachments (`is_inline = 1`) from strict filename/size assertions, since inline images (tracking pixels, logos, signatures) legitimately have empty filenames.

These fixes let the E2E suite pass on real Gmail accounts without schema changes. The junction table remains the correct long-term fix for folder-aware browsing (see above).