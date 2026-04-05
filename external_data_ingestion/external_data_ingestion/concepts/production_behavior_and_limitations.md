# Production behavior and limitations

## Observed production run

All timings below are from a real production run against a Gmail account with **36,508 INBOX messages** and **10 IMAP folders** (including `[Gmail]/All Mail` which is skipped).

## Daemon lifecycle

### Cold start (fresh DB)

| Time | Phase | What | Duration |
|---|---|---|---|
| 21:25:28 | Start | Daemon started, config loaded, DB initialized | instant |
| 21:25:30 | Folder discovery | 10 folders discovered via RFC 6154 flags, cached (5-min TTL) | 2s |
| 21:25:30 | Priority: INBOX | Full bodies, 1,449 messages (90-day `SINCE` filter), 1 reused connection | 1m 19s |
| 21:26:49 | Priority: Sent | Full bodies, 4 messages fetched, 3 inserted | 3s |
| 21:26:53 | **System usable** | 1,452 emails with full bodies — INBOX and Sent browsable and searchable | |
| 21:26:53 | Tasks spawned | IDLE (immediate), Backfill (immediate), Periodic sync (deferred) | instant |
| 21:26:54 | Backfill step 1: INBOX headers | `full=True`, 36,508 fetched, 35,055 new inserts (rest are INSERT OR IGNORE) | 15m 6s |
| 21:42:00 | Backfill step 1: Sent headers | 214 fetched, 208 new inserts | 7s |
| 21:42:10 | Backfill step 2 | Headers for 6 remaining folders (Drafts 18, Important 1,142→11 new, Spam 26, Starred 16→0 new, Trash 0, Unwanted 0) | 43s |
| 21:42:55 | Backfill step 3 | Body upgrade: only Spam had 26 content_level=0 rows in 90-day window | 4s |
| 21:43:00 | Backfill step 4 | Integrity: 37,924 server UIDs, 36,770 local, 0 missing, 1,154 cross-folder. **ok=True** | 53s |
| 21:43:52 | **Fully synced** | `backfill_done` event → deferred periodic sync unblocked | |
| 21:43:53 | Periodic sync #1 | All 8 folders incremental, 0 new messages, ~18s total | 20s |
| 21:45:53 | Integrity #1 | 37,924 server / 36,770 local, ok=True | 1m 40s |
| 21:50:55 | Periodic sync #2 | Folder cache expired (>5 min), re-discovered. 8 folders, 0 new, ~18s | 18s |
| 21:52:06 | Integrity #2 | ok=True | 52s |

**Cold start total: ~18.5 minutes** from daemon start to fully synced + verified.
**Time to usable: ~1.5 minutes** — INBOX and Sent available with full bodies.

### Steady-state cycle (observed)

Once fully synced, the daemon runs a repeating loop:

```
periodic sync (8 folders, ~18s) → integrity check (~1 min) → sleep 5 min → repeat
```

Each steady-state cycle borrows **1 connection** from `ConnectionProvider` (reused across all folders via `mb=`), fetches 0-1 UIDs per folder (IMAP boundary check, not real messages), inserts 0 rows when nothing is new. The connection is returned to the idle pool on completion and may be reused by the integrity check (via NOOP health check) without a fresh login.

IDLE runs concurrently on a separate connection that is proactively cycled every ~25 minutes (each `idle.wait()` blocks for 5 min; after ~5 iterations the connection is returned and re-acquired with a NOOP health check). This prevents Gmail's ~29-minute IDLE timeout from killing the connection unexpectedly. When new mail arrives, IDLE triggers an immediate INBOX sync — no need to wait for the periodic cycle.

**Observed steady-state resource usage:**
- 2 IMAP connections at peak (IDLE + periodic sync or integrity check)
- ~18 seconds per periodic sync cycle
- ~1 minute per integrity check
- 5-minute sleep between cycles

### Folder cache behavior (observed)

The `FolderCache` TTL is 5 minutes. In the production run:

- **21:25:30** — First discovery (cold), cached
- **21:42:10** — Cache expired (~17 min later), re-discovered for backfill step 2
- **21:43:53** — Cache hit (1.5 min old) for periodic sync #1
- **21:50:55** — Cache expired (~8 min later), re-discovered for periodic sync #2

Each re-discovery issues one IMAP `LIST` command (~2 seconds). Syncs within the 5-minute window share the cached result.

### Warm start (existing DB, restart after Ctrl+C or crash)

| Phase | What | Expected time |
|---|---|---|
| Priority sync | INBOX + Sent incremental (`UID last_uid+1:*`). Fetches only messages arrived since last run. | ~3-5 seconds |
| **System usable** | Immediately — all prior data is intact in SQLite | |
| Backfill step 1 | `full=True` re-fetches all header UIDs from server. `INSERT OR IGNORE` skips existing rows. **Zero useful inserts but full IMAP cost.** | ~15 min |
| Steps 2-4 | Incremental. Most folders already have `sync_state`, fetch only new UIDs. | ~2 min |
| Steady state | Same as cold start | continuous |

### Ctrl+C (SIGINT) shutdown sequence

1. `request_stop()` sets `stop_event` + kills IDLE sockets via `force_close()` + calls `provider.force_disconnect_all()` on each account (drains idle pool, marks provider closed)
2. IDLE task: thread unblocks immediately from `idle.wait()`, `connection()` context manager destroys the dead connection, exits
3. Backfill task: finishes current `sync_folder` call, checks `stop_event`, exits. Sets `backfill_done` event.
4. Deferred periodic sync: `asyncio.wait` races `stop_event`, unblocks immediately, exits
5. `wait_stopped(timeout=15)`: waits for tasks, cancels stragglers, closes DB
6. PID file removed

**Total shutdown time: ~2-5 seconds** (dominated by the currently-running IMAP fetch completing). Observed in the integration test: `daemon_shutting_down` → `idle_stopped` → `backfill_done` → `daemon_stopped` in under 3 seconds.

### Hard kill (SIGKILL, power loss, OOM)

- SQLite WAL mode guarantees atomic transactions. Either a `sync_folder` batch committed fully or not at all.
- `sync_state.last_uid` is committed at the end of each `sync_folder` call. If the process dies mid-fetch (after IMAP download but before commit), those messages are lost from the transaction and re-fetched on restart.
- PID file is not cleaned up. `is_daemon_running()` detects stale PID files via `os.kill(pid, 0)` and removes them.
- No data corruption — SQLite WAL journal recovery happens automatically on next open.

## What persists across restart

| Data | Storage | Resume behavior |
|---|---|---|
| All emails (headers + bodies) | `emails` table | `INSERT OR IGNORE` — duplicates are idempotent |
| Sync progress per folder | `sync_state` (`last_uid`, `uidvalidity`) | Incremental sync resumes from `last_uid + 1` |
| Attachment metadata | `attachments` table | Linked to `emails.id`, survives restart |
| Event log | `events` table | Append-only, never re-processed |
| Account config | `config.yaml` + `accounts` table | Config file is never modified by the daemon |

## What does NOT persist

| State | Impact on restart |
|---|---|
| Which backfill phase was active | Backfill restarts from step 1 every time |
| Folder discovery cache | Rediscovered from IMAP on first use |
| IDLE connection | Reconnects fresh |
| Connection pool (idle connections, semaphore permits) | Recreated per event loop via `get_provider()` |
| Health counters (`last_sync_at`, `consecutive_errors`) | Reset to zero |
| `backfill_done` event state | Periodic sync waits for backfill again |

## Integrity verification (observed)

The integrity check compares local DB rows against server UIDs for every selectable folder (except All Mail). Gmail's label system means the same message appears in multiple IMAP folders under different UIDs. The check resolves this by fetching Message-ID headers for candidate "missing" UIDs and cross-referencing against all local `message_id` values.

Observed results from production run:

```
Folder                               Server   Local  Missing  XFolder
INBOX                                 36508   36504       0        4
[Gmail]/Important                      1142      11       0     1131
[Gmail]/Sent Mail                       214     211       0        3
[Gmail]/Starred                          16       0       0       16
[Gmail]/Drafts                           18      18       0        0
[Gmail]/Spam                             26      26       0        0
Unwanted                                  0       0       0        0
[Gmail]/Trash                             0       0       0        0
TOTAL                                 37924   36770       0     1154
```

- **Missing = 0 everywhere** — no data loss
- **XFolder = 1,154** — messages stored under one folder but present in others on the server (Gmail labels). Not gaps.
- **INBOX 36,508 vs 36,504** — 4 duplicate `message_id` deliveries within INBOX itself, correctly deduplicated by `INSERT OR IGNORE`

## Known limitations

### 1. Backfill always re-runs from step 1 on restart

`_backfill_account` has no persistent checkpoint of which step it completed. On every daemon start it runs the full 4-step sequence. Steps 2-4 are incremental (use `last_uid`), but step 1 uses `full=True` which ignores `last_uid` and re-fetches all UIDs from the server.

**Observed cost**: 36,508 headers re-fetched over ~15 minutes on every restart. Zero new rows inserted (`INSERT OR IGNORE`). Pure waste of IMAP time and bandwidth.

**Impact**: Wasted time and bandwidth on restart. Not a correctness issue.

**Possible fix**: Check if `sync_state` already has a `last_uid` for INBOX/Sent and skip `full=True` on warm starts, or persist a `backfill_completed` flag in the DB.

### 2. Single-folder storage (no junction table)

Each email is stored under one `mailbox` — whichever folder synced it first. Gmail exposes the same message in multiple IMAP folders (labels), but the DB stores it once.

**Observed impact** (from production run):
- `[Gmail]/Important` has 1,142 messages on the server but only 11 in local DB — the other 1,131 are stored under INBOX
- `[Gmail]/Starred` has 16 messages on the server but 0 in local DB — all 16 are stored under other folders
- `[Gmail]/Sent Mail` has 214 server-side but only 211 locally — 3 are stored under INBOX (sent-to-self)

This means:
- `get_recent("[Gmail]/Important")` returns almost nothing
- `get_unread_count("[Gmail]/Starred")` returns 0
- `list_folders` only shows folders that "won" at least one message

**Impact**: Folder-aware browsing and counts are unreliable. Content search by `message_id` is unaffected.

**Possible fix**: Add an `email_folders` junction table (see `current_design_folders_gap.md`).

### 3. Priority sync downloads full bodies (slow for large inboxes)

The priority pass fetches full RFC822 bodies for all messages in the 90-day window.

**Observed**: 1,449 messages took 1m 19s. Time scales linearly — an inbox with 5K messages in the 90-day window would take ~4-5 minutes before the system becomes usable.

**Impact**: Time-to-usable scales linearly with message count and average message size in the recent window.

**Possible fix**: Fetch headers-first in the priority pass (making the system browsable in seconds), then upgrade bodies in a background pass.

### 4. No per-folder body-upgrade tracking

`upgrade_folder_bodies` queries `content_level = 0 AND date >= cutoff` each time it runs. There's no persistent flag saying "this folder's 90-day bodies are fully upgraded."

**Observed**: In the production run, only `[Gmail]/Spam` had 26 rows to upgrade (4 seconds). All other folders had 0 eligible rows. On restart, it would re-query all folders again (idempotent but redundant).

**Impact**: Minor — body upgrade is fast for small message counts. Only significant if the daemon restarts frequently during initial sync of a large account.

### 5. `full=True` re-fetches all UIDs from IMAP

When `sync_folder(full=True)` is called, it sets `criteria = "ALL"` and downloads the full UID + header listing from the server, regardless of what's already local. The DB layer deduplicates via `INSERT OR IGNORE`, but the IMAP transfer is the bottleneck.

**Observed**: 36,508 messages = ~730 IMAP round-trips (at `bulk=50`) = 15 minutes. This runs on every daemon start as backfill step 1.

### 6. Single IMAP connection per multi-folder operation

`sync_all_folders`, `upgrade_all_folders_bodies`, and `verify_integrity` each use one connection and iterate folders sequentially. This is correct for connection budget management but means folder sync is not parallelized.

**Observed**: 8 folders in ~18 seconds for periodic sync (incremental). 6 folders in ~43 seconds for backfill step 2 (headers-only, includes 1,142-message Important folder).

**Impact**: Sync time scales linearly with the number of folders. For most accounts (8-12 folders), this is fine. For accounts with 50+ custom folders, it could be slow.

### 7. Attachment payloads are always lazy-fetched

Attachments are stored as metadata rows (`payload IS NULL`) during sync. The actual bytes are fetched on-demand via `EmailClient.download_attachment()`. There's no background pre-fetch of attachment payloads.

**Impact**: First access to an attachment requires an IMAP round-trip. Subsequent accesses are served from the local DB/disk.

### 8. No multi-process DB locking

The daemon and `EmailClient` share the SQLite DB via WAL mode, which supports one writer + many readers. If two daemon processes accidentally run against the same DB (e.g., stale PID file race), writes could conflict.

**Impact**: The `is_daemon_running()` check prevents this in normal operation. Edge case with rapid stop/start cycles.

### 9. Per-account semaphore is per-process, not cross-process

`ConnectionProvider` is scoped to a single event loop via `get_provider()` (keyed by `id(asyncio.get_running_loop())`). When `EmailClient` runs in a separate process (e.g. an external consumer in a FastAPI worker), it gets its own provider with its own `Semaphore(3)`. The daemon's semaphore does not control the client's connections and vice versa.

**Impact**: The daemon (peak 2 connections) + `EmailClient` in another process (0–1 connections for sub-second on-demand fetches) = peak 3 total — well within Gmail's limit. When both run in the same process (e.g. integration tests), they share the same provider and semaphore.

### 10. Gmail's 15-connection limit shared with other clients

The `ConnectionProvider` semaphore (max 3) controls connections from this daemon only. Other IMAP clients (Apple Mail, Thunderbird, phone apps, other automation) also count toward Gmail's 15-connection limit. The daemon cannot know about or control external clients.

**Impact**: If the user has many IMAP clients, the daemon's retry-with-backoff will handle transient limit hits, but persistent contention could cause delays. The backoff sequence is 5s, 10s, 20s, 40s (4 attempts max). Failed login attempts now force-close the raw socket immediately, preventing zombie TCP connections from compounding the problem.

### 11. No incremental FTS index rebuild

The FTS5 index is maintained via triggers on INSERT/UPDATE/DELETE. If the FTS index becomes corrupted (rare), there's no built-in `REBUILD` command exposed. Manual SQLite intervention would be required (`INSERT INTO emails_fts(emails_fts) VALUES('rebuild')`).

### 12. Periodic sync includes `skip_roles={"all"}` but periodic integrity does not skip All Mail consistently

Both periodic sync and periodic integrity check skip All Mail via `skip_roles={"all"}`. This is consistent. However, the `skip_roles` parameter is a set of RFC 6154 role strings, not folder names. If a provider uses a non-standard role, the skip logic would miss it.

**Impact**: Negligible for Gmail. Could matter for exotic IMAP providers.

## Operational notes

### Monitoring

- `daemon.health()` returns per-account sync status, error counts, and timestamps
- `events` table records `new_email`, `sync_complete`, `sync_error`, `integrity_check` events
- Structured logs via `structlog` include account, folder, message counts, and timing
- Integrity results are logged as `backfill_integrity_ok` / `periodic_integrity_ok` / `*_gaps`

### Disk usage

- `emails.db` grows proportionally with message count. Headers-only rows are ~2-5 KB each. Full-body rows vary widely (1 KB for plain text, 100+ KB for HTML newsletters).
- For 36K messages (35K headers-only + 1.5K with bodies): expect ~200-400 MB for the DB file.
- Attachments stored on disk (>1 MB) are in `attachments/`. Smaller attachments are in the `attachments.content_blob` column.

### IMAP connection budget

- `ConnectionProvider` per account: semaphore (max 3 concurrent) + idle pool with NOOP health checks
- All connections borrowed via `async with provider.connection() as mb:` — guaranteed cleanup on error
- **TCP keepalive** on every socket: 60s idle, 10s probe interval, 3 probes — dead connections detected in ~90s instead of 10-30 min
- **IDLE cycling**: connection recycled every ~25 min (5-min wait × ~5 iterations) — prevents Gmail's 29-min timeout, detects silently-dead connections
- Observed steady-state peak: 2 (IDLE + periodic sync/integrity)
- Observed cold-start peak: 2 (IDLE + backfill)
- Login retry: 4 attempts with exponential backoff (5s, 10s, 20s, 40s) for "Too many simultaneous connections"
- Failed logins force-close the raw socket (`socket.shutdown(SHUT_RDWR)`) to prevent zombie TCP connections
- See `imap_connection_budget.md` for full design details.

### Recovery

- **Network drop (lid closed, sleep, Wi‑Fi)**: TCP keepalive detects the dead connection within ~90s and tears down the socket (freeing Gmail's server-side slot). IDLE reconnects with backoff; periodic sync retries every 5 min. See `network_recovery_and_concurrent_tasks.md` for details.
- **Corrupted DB**: Delete `emails.db` and restart. Full re-sync from IMAP.
- **Stale PID file**: `is_daemon_running()` auto-detects dead processes and cleans up. Or manually delete `daemon.pid`.
- **Connection limit errors**: Daemon retries automatically with exponential backoff. TCP keepalive ensures zombie connections are freed within ~90s. Close other IMAP clients if persistent.
- **Reset everything**: `uv run email-sync-daemon reset --all --yes` wipes DB, attachments, and config.
- **Partial sync (crashed mid-backfill)**: Restart the daemon. Priority sync resumes instantly via `last_uid`. Backfill re-runs from step 1 but `INSERT OR IGNORE` ensures no duplicates.
