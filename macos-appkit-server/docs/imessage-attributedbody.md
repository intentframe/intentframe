# iMessage Reading on macOS Tahoe (26+)

How `MessagesService.READ_MESSAGES` extracts message text from `chat.db`,
why the obvious approach silently broke on macOS Tahoe, and how the fix
works end-to-end.

## TL;DR

- On macOS 26 (Tahoe), Apple stopped populating `message.text` in
  `~/Library/Messages/chat.db`. The actual content lives only in
  `message.attributedBody`, an `NSArchiver` typedstream blob.
- We `SELECT` both columns, `OR`-relax the `WHERE`, and decode the
  blob via [Madrid](https://github.com/loopwork-ai/Madrid)'s `TypedStream`
  module — a pure-Swift parser for Apple's legacy typedstream format.
- The fix lives entirely in
  [`Sources/Services/MessagesService.swift`](../Sources/Services/MessagesService.swift)
  and a one-line `Package.swift` dependency.
- Pre-Tahoe macOS still works — the SQL accepts rows where either
  column is populated, and the decoder is only called when `text` is NULL.

## Symptom

Before the fix, on macOS 26.x:

```bash
curl -sS --unix-socket "$HOME/.intentframe/run/platform.sock" \
  -X POST http://localhost/execute \
  -H 'Content-Type: application/json' \
  -d '{"adapter":"messages","action":"READ_MESSAGES","params":{"limit":3}}'
```

returned `{"messages": [], "count": 0}` for every query — even an
empty-contact dump that should have returned the latest messages from
any conversation. Full Disk Access was granted, the `chat.db` file was
present and recently modified, the SQLite open succeeded — and the
SQL still matched zero rows.

## Root cause

`chat.db` schema has had **two** message-text columns for years:

| Column | What's in it |
|---|---|
| `message.text` | Plain UTF-8 string |
| `message.attributedBody` | `NSAttributedString` serialized via `NSArchiver` (typedstream binary format) |

Pre-Tahoe macOS populated *both*, so a query like
`WHERE m.text IS NOT NULL` worked fine and `attributedBody` could be
ignored. On macOS 26 Tahoe, Apple stopped populating `message.text`
for almost every row. The content now lives **only** in
`attributedBody`, and any query gated on `m.text IS NOT NULL` silently
returns zero rows.

This is a behavior change Apple made in the OS, not a bug in our
SQLite path. There's no schema migration to detect — the columns
look identical, only the per-row population pattern changed.

## Why the obvious decoder doesn't work

`attributedBody` looks like it should be decodable with
`NSKeyedUnarchiver` since that's the modern Foundation API for
unarchiving objects. **It can't.** The blob is the *legacy*
`NSArchiver` "typedstream" format — a different binary protocol
predating keyed archives. Bytes 2–12 of any `attributedBody` blob
spell out the ASCII signature `streamtyped` (after a 2-byte version
header), confirming the format.

The historical decoder is `NSUnarchiver`. Apple deprecated it in
macOS 10.13 and **never bridged it to Swift** — it exists only as an
Objective-C class with no Swift surface. Even calling it from Swift
via `NSClassFromString` + selector dispatch is fragile and depends on
a deprecated symbol that Apple could remove at any release.

So the practical options are:

1. Hand-roll a typedstream parser inside `MessagesService.swift`
   (~100 lines of bit-twiddling we'd own forever).
2. Bridge to Objective-C with a tiny wrapper target around
   `NSUnarchiver` (mixed-language target, deprecated symbol).
3. Use a pure-Swift typedstream library written by someone else.

Option 3 is the only one with no maintenance burden and no deprecated
symbols, provided such a library exists. As of April 2026, exactly
one does: [Madrid](https://github.com/loopwork-ai/Madrid).

## Madrid

[Madrid](https://github.com/loopwork-ai/Madrid) is a Swift package by
[Mattt Thompson](https://mattt.me) (loopwork-ai). It exposes two
library products:

- `TypedStream` — a pure-Swift parser for Apple's typedstream binary
  format. No dependencies. No Apple legacy symbols. Builds on
  Linux too (though we only use it on macOS).
- `iMessage` — a higher-level wrapper that reads `chat.db` directly.
  We do **not** depend on this product, only on `TypedStream`,
  because we already have our own SQLite path in `MessagesService`
  and don't need a second one.

We pin Madrid at `from: "0.4.0"`. SwiftPM resolves the highest
matching tag once and pins it in `Package.resolved`, which is
checked into git for reproducibility. To bump Madrid in the future,
run `swift package update Madrid` from `macos-appkit-server/`,
verify `READ_MESSAGES` still works with the curl tests below, and
commit the updated `Package.resolved`.

We deliberately do **not** auto-update Madrid on every build —
Madrid is in 0.x, where minor version bumps are allowed to break
the API under SemVer. A silent auto-update could break iMessage
reading at exactly the moment you most need it working.

## The fix

Three things change in
[`Sources/Services/MessagesService.swift`](../Sources/Services/MessagesService.swift):

### 1. SQL — both queries

```sql
SELECT
    c.display_name,
    -- name/identifier column,
    m.text,
    m.attributedBody,        -- ← new
    m.date as message_date,
    m.is_from_me,
    m.service
FROM ...
WHERE ...
  AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
ORDER BY m.date DESC
LIMIT ?
```

The relaxed `WHERE` clause is the load-bearing change: it accepts
both legacy rows (where `text` is populated) and Tahoe rows (where
only `attributedBody` is populated). Rows where neither is populated
(reactions/tapbacks, system messages, attachment-only) are still
excluded.

### 2. Per-row text extraction

```swift
let text: String = {
    // Legacy / pre-Tahoe path: m.text is populated.
    if let raw = sqlite3_column_text(stmt, 2).map({ String(cString: $0) }) {
        return raw
    }
    // macOS Tahoe 26+: m.text is NULL, content lives in attributedBody.
    if sqlite3_column_type(stmt, 3) == SQLITE_BLOB,
       let blob = sqlite3_column_blob(stmt, 3) {
        let len = Int(sqlite3_column_bytes(stmt, 3))
        if len > 0 {
            let data = Data(bytes: blob, count: len)
            return Self.decodeAttributedBody(data) ?? ""
        }
    }
    return ""
}()
```

`m.text` is tried first. The decoder only runs when `text` is NULL,
which means pre-Tahoe machines never pay the parsing cost.

### 3. The decoder helper

```swift
import TypedStream

private static func decodeAttributedBody(_ data: Data) -> String? {
    guard let parts = try? TypedStreamDecoder.decode(data) else { return nil }
    let joined = parts.compactMap { $0.stringValue }.joined(separator: "\n")
    return joined.isEmpty ? nil : joined
}
```

This is the canonical extraction pattern from Madrid's own
`Database.swift` consumer:

- `TypedStreamDecoder.decode(_:)` is a static throwing method that
  walks the typedstream graph and returns `[Archivable]`.
- `Archivable.stringValue` is a Madrid-side accessor that filters
  out class-metadata strings (`"NSAttributedString"`,
  `"__kIMMessagePartAttributeName"`, etc.) and only returns
  strings that look like real message text.
- `compactMap` keeps only the non-nil string values, then `joined`
  concatenates them — necessary because messages with attribute
  runs (formatting, links, mentions) are stored as multiple
  `NSString` chunks in the same blob.

## Empty-name fallback

While debugging the typedstream issue, we noticed that even after
text was decoding correctly, the `name` field on every returned
message was the empty string. The reason:

For 1:1 chats, macOS often stores `chat.display_name` as the empty
string `""` rather than NULL. The previous code was:

```swift
nameOrId = sqlite3_column_text(stmt, 0).map { String(cString: $0) }
    ?? sqlite3_column_text(stmt, 1).map { String(cString: $0) }
    ?? "Unknown"
```

`sqlite3_column_text` returns a non-NULL pointer to an empty C
string when the column value is `""`, so `.map` runs and the
fallback to column 1 never fires. The fix treats empty strings as
missing:

```swift
let nameOrId: String = {
    let primary = sqlite3_column_text(stmt, 0).map { String(cString: $0) } ?? ""
    if !primary.isEmpty { return primary }
    let secondary = sqlite3_column_text(stmt, 1).map { String(cString: $0) } ?? ""
    if !secondary.isEmpty { return secondary }
    return "Unknown"
}()
```

So 1:1 chats now surface the chat identifier (e.g.
`+918471863537`) or handle id (e.g. `someone@example.com`) instead
of `""`. Group chats with a real `display_name` keep working
unchanged. We also collapsed the `if hasContact / else` duplication
since both branches read the same column indices.

## Quirks worth knowing

- **Madrid's `"NS"` substring filter.** `Archivable.stringValue`
  drops any string containing `"NS"` to filter out class-metadata
  noise like `"NSAttributedString"`. This means a real message
  containing `"NS"` (e.g. *"NSE is closed today"*) will be silently
  dropped. Edge case, but worth knowing if a user reports a missing
  message.
- **Tapbacks, attachments, stickers.** Messages with no text
  payload (a 👍 reaction, an attachment-only message, a sticker)
  may produce an empty decoder output and fall through to `""`.
  This matches the legacy `m.text IS NULL` behavior, so it's not a
  regression — just a known limitation.
- **`Package.resolved` is checked in.** A fresh `git clone`
  arrives with Madrid's version pinned. Running
  `bash intentframe_setup.sh` does **not** auto-update Madrid; you
  have to opt in with `swift package update Madrid` from
  `macos-appkit-server/`.

## Verifying the fix

After any change to `MessagesService.swift`, rebuild and re-run
both curls:

```bash
bash macos-appkit-server/Scripts/bundle.sh

# Empty contact — should return the latest N messages from any conversation
curl -sS --unix-socket "$HOME/.intentframe/run/platform.sock" \
  -X POST http://localhost/execute \
  -H 'Content-Type: application/json' \
  -d '{"adapter":"messages","action":"READ_MESSAGES","params":{"limit":3}}' \
  | python3 -m json.tool

# Contact filter — substring match against display_name or handle id
curl -sS --unix-socket "$HOME/.intentframe/run/platform.sock" \
  -X POST http://localhost/execute \
  -H 'Content-Type: application/json' \
  -d '{"adapter":"messages","action":"READ_MESSAGES","params":{"contact":"Abhilasha","limit":5}}' \
  | python3 -m json.tool
```

A healthy response has:

- `data.count > 0`
- Each `messages[i].text` is the real message body (not `""`)
- Each `messages[i].name` is either a chat display name, a phone
  number / email handle, or `"Unknown"` (not `""`)

If `count` is zero, the SQL is the suspect: check that
`Sources/Services/MessagesService.swift` still has
`OR m.attributedBody IS NOT NULL` in both queries.

If `count > 0` but `text` is empty, the decoder is the suspect:
either `Madrid` is unresolved (run `swift package resolve` from
`macos-appkit-server/`), or Madrid's API has changed (read
`Package.resolved` to see the pinned version, then check Madrid's
release notes).

If `name` is empty, the empty-string fallback was reverted — check
that `MessagesService.swift` treats empty strings as missing in the
`nameOrId` closure, not just NULL.

## When Madrid breaks

If Madrid ever ships a 0.x release that breaks our integration, the
fallback is to either:

1. **Pin tighter.** Change `from: "0.4.0"` to
   `.upToNextMinor(from: "0.4.0")` in `Package.swift` to block
   minor bumps.
2. **Hand-roll a parser.** The typedstream format is documented in
   [Chris Sardegna's reverse-engineering writeup](https://chrissardegna.com/blog/reverse-engineering-apples-typedstream-format/).
   The Rust [`imessage-database`](https://docs.rs/imessage-database/latest/imessage_database/util/streamtyped/fn.parse.html)
   crate's `streamtyped::parse` function is the gold-standard
   reference implementation; it's small enough to port to Swift in
   ~150 lines.

Both fallbacks are documented here as escape hatches, not as
recommendations. The current Madrid integration is the right shape
as long as Madrid stays maintained.

## File-level reference

| What | Where |
|---|---|
| Madrid dependency line | [`Package.swift`](../Package.swift) |
| `import TypedStream` | [`Sources/Services/MessagesService.swift`](../Sources/Services/MessagesService.swift) |
| SQL with `attributedBody` | [`Sources/Services/MessagesService.swift`](../Sources/Services/MessagesService.swift) (`readMessages` function) |
| `decodeAttributedBody` helper | [`Sources/Services/MessagesService.swift`](../Sources/Services/MessagesService.swift) (Helpers section) |
| Empty-name fallback | [`Sources/Services/MessagesService.swift`](../Sources/Services/MessagesService.swift) (inside the `sqlite3_step` loop) |
| Build script (auto-restarts the running server) | [`Scripts/bundle.sh`](../Scripts/bundle.sh) |
