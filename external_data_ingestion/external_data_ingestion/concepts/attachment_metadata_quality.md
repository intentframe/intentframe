# Attachment metadata quality

## What the attachment table stores

Every MIME part that is not the email body is stored as a row in the `attachments` table:

```
attachments
┌──────────┬──────────────┬────────────┬──────────┬───────────┬───────────┐
│ email_id │ content_type │  filename  │size_bytes│ is_inline │  payload  │
└──────────┴──────────────┴────────────┴──────────┴───────────┴───────────┘
```

Key columns:

- `filename` — from `Content-Disposition: attachment; filename="..."` or `Content-Type: ...; name="..."`. Can be empty when the header is absent.
- `size_bytes` — byte length of the decoded payload. Zero when the part has no payload (e.g. a structural MIME part).
- `is_inline` — `1` for `Content-Disposition: inline` parts (typically embedded images). `0` for explicit attachments.
- `payload` — stored lazily; `NULL` until fetched on-demand. Metadata rows have `payload IS NULL`.

## Why some rows have empty filenames or zero size

Real-world email MIME structures are messier than the spec implies. The following types legitimately have empty filenames or zero/unknown size:

| Content type | Reason |
|---|---|
| `image/*` (inline) | Tracking pixels, logos, signatures — embedded in the body, no filename |
| `application/pkcs7-signature` | S/MIME detached signature block — no filename, small fixed payload |
| `text/calendar` | iCal invite — often delivered without a filename header |
| `application/octet-stream` | Generic binary with no `Content-Disposition: filename` |
| Any `multipart/*` structural part | Zero-length container node, not actual content |

These are **valid MIME structures**, not parsing bugs.

## Invariants enforced by the E2E test

`test_09c_attachment_metadata` enforces two checks with different severity:

### Hard assertion (structural correctness)

Every email row with `has_attachments = 1` must have at least one row in the `attachments` table.

```sql
SELECT COUNT(*) FROM attachments WHERE email_id = ?
```

Failure here means the sync engine is not persisting attachment metadata at all, which is a real bug.

### Soft warning (metadata quality)

Attachment rows with `filename = ''` or `size_bytes <= 0` are counted and printed, but **do not fail the test**. The warning breaks down counts by `is_inline` flag and lists the content types of non-inline offenders, so you can see if something unexpected is missing filenames.

```
Note: 74 attachment rows with empty filename or zero size (4 inline, 70 non-inline)
  Non-inline content types: {'application/pkcs7-signature': 45, 'text/calendar': 18, ...}
```

This is intentionally a warning rather than an assertion because the variety of "legitimate empty filename" content types grows with real account data and no whitelist is exhaustive.

## What would be a real bug

These are cases that would indicate a parsing or storage defect and should be investigated:

- `has_attachments = 1` but zero rows in `attachments` (caught by hard assertion)
- A `application/pdf` or `image/png` non-inline part with `filename = ''` — PDFs and PNGs always carry a name
- `size_bytes = 0` for a non-inline part with a non-empty payload — mismatch between stored size and actual content
- `is_inline = 0` but `payload IS NULL` after an explicit download request — lazy fetch failure

## Relationship to the folders gap

The attachment metadata issue is independent of the Gmail multi-label / junction table gap described in `current_design_folders_gap.md`. Attachments are linked to `emails.id`, not to `mailbox`, so the folder deduplication behaviour does not affect attachment storage.
