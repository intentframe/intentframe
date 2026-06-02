# Email Sync Service

Background IMAP sync daemon with real-time IDLE notifications and a direct-read async client library. Emails are stored in a local SQLite database (WAL mode, FTS5 full-text search) and kept in sync with the remote IMAP server.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                SyncDaemon                                     │  ← owns the workspace
│                                                              │
│  ConnectionProvider (per-account, from imap_connection.py)    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Semaphore(3) — caps concurrent IMAP connections      │    │  avoids Gmail's 15-conn limit
│  │ Idle pool    — reuses healthy connections (NOOP)     │    │  fewer logins, faster ops
│  │ FolderCache  — TTL-based (5 min), avoids re-LIST     │    │  shared across all phases
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  Priority sync (blocking, 1 connection):                     │
│  ┌─────────────────────────────────────────┐                 │
│  │ discover → INBOX → Sent (reuse conn)    │                 │  server-side date filter (fast)
│  └─────────────────────────────────────────┘                 │
│                                                              │
│  Background (staggered):                                     │
│  ┌────────────┬────────────┬────────────────────┐            │
│  │ IDLE loop  │  Backfill  │  Periodic sync     │            │  IDLE = immediate
│  │ (INBOX)    │  (one-shot │  (waits for        │            │  backfill = one-shot
│  │            │   + verify)│  backfill to end)  │            │  periodic = 5 min after backfill
│  └─────┬──────┴──────┬─────┴──────────┬─────────┘            │
│        │  async with provider.connection() as mb:            │  context-managed + retry
│        │   imap-tools │               │                      │  synchronous lib via to_thread()
│        └──────┬───────┴───────────────┘                      │
│           SQLite (WAL)                                       │  shared database
└──────────────────────────────────────────────────────────────┘
         ▲
         │ direct reads (sub-ms) + on-demand IMAP fetch
         │
┌────────┴─────────────────────────────────────┐
│        EmailClient()                         │  ← zero-arg, email addresses only
│  list, search, send, reply, forward, draft   │
│  get_email (lazy body fetch; headers_only)   │
│  download_attachment (lazy payload fetch)     │
└──────────────────────────────────────────────┘
```

- **Daemon** runs as a separate process. All IMAP connections are obtained through a centralised `ConnectionProvider` (one per account, in `imap_connection.py`) that enforces a concurrency cap (default 3 via semaphore), reuses idle connections via a health-checked pool, and retries with exponential backoff on connection-limit errors — see [`imap_connection_budget.md`](external_data_ingestion/concepts/imap_connection_budget.md) for full design details. Every connection is borrowed through an `async with provider.connection() as mb:` context manager that guarantees cleanup (logout + raw socket close) on error. Initial sync fetches full content (headers + bodies) for INBOX and Sent over a single reused connection with a server-side date filter — the system is usable within minutes. A background backfill task then syncs remaining folders' headers and bodies. `[Gmail]/All Mail` is skipped (redundant with individual folders). IDLE starts immediately for real-time notifications; periodic sync is deferred until backfill completes to avoid redundant work. After backfill and after every periodic sync, the system automatically verifies data integrity by comparing local UIDs against the IMAP server — gaps are logged and recorded as events.
- **Client** reads directly from the daemon's shared SQLite file. Writes (send, reply, draft, move, delete) go through IMAP/SMTP via `imap-tools` and `aiosmtplib`. When a consumer reads a headers-only message, the client transparently fetches the full body from IMAP. Attachment payloads are always fetched on-demand. All IMAP connections opened by the client go through `ConnectionProvider`, so they share the daemon's connection pool and semaphore when running in the same process (e.g. tests), or get their own independent pool when running in a separate process (e.g. an external consumer). See [`imap_connection_budget.md`](external_data_ingestion/concepts/imap_connection_budget.md) § "Cross-process connection budget" for details.
- **Folder discovery** uses RFC 6154 special-use flags — no hardcoded folder names. Discovered folder lists are cached (5-minute TTL) so repeated operations within a phase don't re-issue IMAP `LIST` commands.

### Attachments

- **Inbound** — Received messages may have attachments; metadata is synced to SQLite and payloads are fetched on demand via `list_attachments` / `download_attachment`.
- **Outbound** — `send`, `reply`, `forward`, and `create_draft` send plain or HTML body only; they do **not** attach local files or re-attach originals from a thread (not implemented yet).

## Prerequisites: Credential Vault

**Passwords are never stored in config files.** EDI fetches them from the running `intentframe_credentials` vault service at startup. The vault must be running before you start the daemon, run the client, or run tests.

```bash
# Start the vault (seeds passwords from .env)
uv run python -m intentframe_credentials.dev_server

# Or with TCP transport (easier for curl/debugging)
uv run python -m intentframe_credentials.dev_server --tcp
```

See the [intentframe_credentials README](../intentframe_credentials/README.md) for how to configure the vault and seed email passwords.

### Credentials in memory and logs

After load, each resolved `AccountConfig` holds the vault password as **`pydantic.SecretStr`**. That way `repr(account)`, traceback locals, and debugger views show a masked value (for example `password=SecretStr('**********')`), not plaintext. Any code that passes the secret into IMAP or SMTP must unwrap it at the boundary with **`account.password.get_secret_value()`**.

The email daemon configures structlog with **`redact_credentials`** from `intentframe_credentials`, which scrubs top-level log keys such as `password` and `token`. That processor does not rewrite secrets that appear only inside another object’s string form; **`SecretStr` on `AccountConfig` is the main guard** against leaks in stack traces.

## Setup

### 1. Install dependencies

From the repository root:

```bash
uv sync
```

### 2. Store the email password in the vault

Passwords live in the vault under namespace `email.<address>`, key `password`. The easiest way is to add the credentials to the vault `.env` file:

```bash
# intentframe_credentials/intentframe_credentials/.env
EMAIL_WORK_ADDRESS=you@gmail.com
EMAIL_WORK_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

Then (re)start the vault. For Gmail, generate an [App Password](https://myaccount.google.com/apppasswords) (requires 2FA enabled).

### 3. Add an email account

```bash
uv run email-sync-daemon add you@gmail.com
```

The vault must be running. The command fetches the password from the vault, validates IMAP login, then writes only the email address to `config.yaml`. Provider settings (Gmail, Outlook, Yahoo, iCloud) are auto-detected from the domain.

For custom IMAP/SMTP settings, edit `~/.intentframe/email/config.yaml` and add `imap_host`, `smtp_host`, `imap_port`, `smtp_port` explicitly.

Or via Python:

```python
from external_data_ingestion.email.config import add_email

# Password must already be in the vault
add_email("you@gmail.com", display_name="Your Name")
```

### Workspace layout

Everything lives under one root (`~/.intentframe/email` by default):

```
~/.intentframe/email/
├── config.yaml      # account list — email addresses only, no passwords
├── emails.db        # SQLite database (created by daemon)
├── daemon.pid       # PID file (managed by daemon start/stop)
└── attachments/     # downloaded attachments (created by daemon)
```

Override with `INTENTFRAME_EMAIL_HOME`:

```bash
INTENTFRAME_EMAIL_HOME=/path/to/workspace uv run email-sync-daemon
```

## Managing accounts

```bash
uv run email-sync-daemon add you@gmail.com      # add account (password fetched from vault, validates IMAP)
uv run email-sync-daemon remove you@gmail.com   # remove account from config
uv run email-sync-daemon list                   # show configured accounts
```

After adding or removing accounts, restart the daemon.

### Resetting the workspace

```bash
uv run email-sync-daemon reset             # wipe DB + attachments, keep config (prompts for confirmation)
uv run email-sync-daemon reset --yes       # same, skip prompt
uv run email-sync-daemon reset --all       # full wipe including config (prompts)
uv run email-sync-daemon reset --all --yes # full wipe, skip prompt (for scripts)
```

If the daemon is running, `reset` stops it automatically before deleting. Default reset keeps `config.yaml` — use `--all` only when you want a true clean slate.

## Running the daemon

```bash
uv run email-sync-daemon start       # or just: uv run email-sync-daemon
uv run email-sync-daemon start --body-days 30   # fetch bodies for last 30 days instead of 90
```

On startup the daemon will:
1. Check for an existing running instance (refuses to double-start)
2. Write a PID file to `EMAIL_HOME/daemon.pid`
3. Load config and initialize the SQLite database
4. **Priority sync** — open one IMAP connection per account, discover folders (caches the result), then fetch full content (headers + bodies) for INBOX and Sent using an IMAP `SINCE` filter for the recent window (default 90 days). The single connection is reused across discovery and both folders — the system is usable within minutes
5. Spawn background tasks in a **staggered** order:
   - **IDLE** — starts immediately for real-time INBOX notifications
   - **Backfill** — fetches old INBOX + Sent headers, then headers + bodies for remaining folders (excluding `[Gmail]/All Mail`), then **verifies integrity** against the IMAP server
   - **Periodic sync** — waits for backfill to finish before starting (avoids redundant overlapping work), then runs every 5 min with **integrity verification** after each cycle
6. All IMAP connections go through `ConnectionProvider.connection()` (a context manager), which enforces a per-account semaphore (max 3 concurrent), reuses healthy idle connections, and retries with exponential backoff on "Too many simultaneous connections" errors. Failed connections are forcefully closed at the socket level to prevent zombie TCP connections. Every socket has **TCP keepalive** enabled (dead connections detected in ~90s). The **IDLE connection cycles every ~25 minutes** (like Apple Mail's ~28-min cycle) to prevent Gmail's server-side timeout and detect silently-dead connections.

The `--body-days` flag overrides `body_sync_days` in `config.yaml` for a single run. Messages older than the window have their headers stored locally; bodies are fetched on-demand when accessed via `EmailClient.get_email()`.

### Stopping the daemon

```bash
uv run email-sync-daemon stop        # sends SIGTERM, waits for clean exit
```

The `stop` command sends SIGTERM to the running daemon and waits up to 15 seconds for it to exit. If the daemon is not running, it reports that and exits cleanly.

Other ways to stop:
- **Ctrl+C** in the terminal running the daemon
- **Programmatically** — use `SyncDaemon.request_stop()` (see below)

### Checking status

```bash
uv run email-sync-daemon status
```

Shows workspace path, whether the daemon is running (with PID), and configured accounts.

### Verifying data integrity

```bash
uv run email-sync-daemon verify
```

Compares every UID on the IMAP server against the local DB for each synced folder (excluding `[Gmail]/All Mail`). Prints a per-folder table and exits with code 1 if gaps are found. This runs the same `verify_integrity()` function that the daemon calls automatically after backfill and after every periodic sync — useful for ad-hoc checks or CI.

## Using the client library

`EmailClient` exposes two construction paths depending on context:

```python
# From async code (event loop already running — daemon, tests, external consumer):
client = await EmailClient.create()

# From sync code (separate process with no event loop — scripts, CLI):
client = EmailClient()
```

```python
import asyncio
from external_data_ingestion.email.client import EmailClient

async def main():
    client = await EmailClient.create()

    # Read operations (from local SQLite — instant for metadata)
    emails = await client.get_recent("you@gmail.com", limit=20)
    unread = await client.get_unread_count("you@gmail.com")
    count = await client.get_message_count("you@gmail.com", "INBOX")
    results = await client.search("invoice", account_email="you@gmail.com")
    thread = await client.get_thread(message_id="<abc@example.com>")
    folders = await client.list_folders("you@gmail.com")

    # get_email transparently fetches the body if only headers are stored locally
    email = await client.get_email("<abc@example.com>")

    # headers_only=True skips lazy body fetch (useful for header probing)
    email = await client.get_email("<abc@example.com>", headers_only=True)

    # download_attachment fetches the payload from IMAP on first access
    data = await client.download_attachment("<abc@example.com>", "report.pdf")

    # Write operations (hit IMAP/SMTP directly)
    await client.send("you@gmail.com", to=["them@example.com"], subject="Hello", body="Hi there")
    await client.reply(message_id="<abc@example.com>", body="Thanks!")
    await client.forward(message_id="<abc@example.com>", to=["other@example.com"])
    await client.create_draft("you@gmail.com", to=["them@example.com"], subject="WIP", body="Draft content")
    await client.mark_read(message_id="<abc@example.com>")
    await client.move(message_id="<abc@example.com>", to_folder="Archive")
    await client.delete(message_id="<abc@example.com>")

    # Event observer
    @client.on("new_email")
    async def on_new(event):
        print(f"New email: {event.data}")

    await client.start_listening()
    # ... later ...
    await client.stop_listening()

    await client.close()

asyncio.run(main())
```

The client takes **no config**. It reads from the daemon's workspace. Every method uses the email address string as the account identifier.

### Discovering available accounts

Three levels of account discovery, depending on what you need:

```python
# 1. Active accounts — configured in config.yaml AND status='active' in the DB.
#    Use this when you need accounts that are fully operational (synced at least once).
#    This is what the executor's MailAdapter uses to validate account_email parameters.
active = await client.get_active_accounts()
for a in active:
    print(a.email, a.provider, a.status)  # status is always 'active'

# 2. All synced accounts — everything the daemon has ever seen (active, error, etc.)
#    Use this for diagnostics or when you need to see accounts in error state.
all_synced = await client.list_accounts()
for a in all_synced:
    print(a.email, a.provider, a.status)

# 3. Configured emails — reads config.yaml directly, daemon not required.
#    Use this for CLI tools or setup wizards that run before the daemon.
from external_data_ingestion.email.config import list_configured_emails
emails = list_configured_emails()  # ["you@gmail.com", "work@outlook.com"]
```

If an operation targets an account that isn't configured, `AccountNotFoundError` is raised with a descriptive message indicating whether the account was never configured or is configured but not yet active.

### IntentFrame executor and Jarvis

The macOS **mail adapter** (`intentframe_native_kit/intentframe_executor_pack_macos/adapters/mail.py`) uses **`get_active_accounts()`** to validate `account_email` on SEND/READ/SEARCH. If those actions arrive **without** `account_email`, the adapter returns failure and the error string includes the current active account emails (same source as `get_active_accounts()`). That gives consumers a hint in logs or error handling; it is **not** a substitute for a first-class “list mail accounts” action in the registry.

**Jarvis** (`jarvis_pa`) exposes email tools with **required** `account_email` parameters (`jarvis/tools.py`), so the LLM is not steered to omit the field to trigger that error path. For end-to-end “discover then read” flows, either the user supplies the address, it is stored in workspace memory, or a future `LIST_EMAIL_ACCOUNTS`-style action and Jarvis tool would be needed. See `jarvis_pa/README.md` → *Email and account discovery*.

### Outbound mail, Sent folder, and local search latency

This section explains why **Apple Mail (or the provider web UI) can show a sent message immediately** while **`EmailClient.search()` may not find it for a short time**.

1. **Send path vs local DB rows** — `send`, `reply`, and `forward` deliver mail via SMTP (`email/actions.py::send_email`). On success they record an `email_sent` **event** in SQLite; they do **not** insert a full mirror row into `emails` as part of that same call. The canonical copy of the message in your mailbox lives on the **IMAP server** (e.g. under the account’s **Sent** folder), and EDI learns about it when **IMAP sync** pulls that folder.

2. **IDLE is INBOX-only** — Real-time IMAP `IDLE` runs on **`INBOX` only** (`email/sync.py::run_idle`). IMAP IDLE is **per selected mailbox**; watching **Sent** in real time would require a **second** long-lived IMAP connection per account. That is a deliberate tradeoff against connection limits (e.g. Gmail’s simultaneous connection cap) and complexity. **Sent** updates are therefore picked up by **folder sync**, not by the IDLE loop.

3. **When Sent appears locally** — After startup priority sync (recent **INBOX + Sent**), ongoing updates to **Sent** arrive primarily through **periodic sync** (every **5 minutes** after backfill completes; see `daemon.py` / `PERIODIC_SYNC_INTERVAL`). Until that run ingests the new UID, the message may be visible in Mail.app but **absent from local FTS search**.

4. **Do not use `[Gmail]/All Mail` as a substitute** — Sync intentionally **skips** the `all` role in many passes (`skip_roles={"all"}`) because Gmail exposes the same logical message under multiple label-folders. The local schema stores **one row per `(account_email, message_id)`** with a single `mailbox` column (`db.py`). Treating All Mail as the primary sync target would **conflate** Inbox/Sent/label semantics and fight `INSERT OR IGNORE` deduplication — see “Priority-first sync” and periodic sync skip lists in this README.

5. **Implications for agents** — Confirming “did my reply send?” should rely on the **SMTP send result** (`success` / `message_id` from the client), not on an immediate `search_email` in **Sent**. Searching for very recent outbound mail may require **`in:sent`** plus patience, or a later retry after sync.

## Using the daemon controller directly

For embedding in a larger application (e.g. intentframe supervisor):

```python
from external_data_ingestion.email.config import load_config_async
from external_data_ingestion.email.daemon import SyncDaemon

config = await load_config_async()   # async — uses VaultClient, safe inside event loop
daemon = SyncDaemon(config, body_sync_days=90)

await daemon.start()        # init DB, priority sync, spawn tasks

# Health check (for supervisor liveness probes)
status = daemon.health()
# {"running": True, "started_at": "...", "pid": 12345,
#  "accounts": {"you@gmail.com": {"last_sync_at": "...", ...}}}

daemon.request_stop()       # non-blocking, kills IDLE sockets instantly
await daemon.wait_stopped() # waits for tasks to finish, closes DB
```

### Terminal lifecycle (without supervisor)

```python
from external_data_ingestion.email.daemon import is_daemon_running, stop_daemon

alive, pid = is_daemon_running()  # checks PID file + os.kill(pid, 0)
if alive:
    stop_daemon()                 # sends SIGTERM
```

## Running tests

Tests require the credential vault to be running and seeded with passwords for the test accounts.

### 1. Start the vault

```bash
uv run python -m intentframe_credentials.dev_server
```

Ensure your test email accounts and passwords are in the vault `.env` before starting.

### 2. Configure test email addresses

Each test suite has its own config file (both gitignored):

| File | Used by |
|---|---|
| `external_data_ingestion/tests/test_config.yaml` | `test_integration.py`, `test_gmail.py` |
| `external_data_ingestion/tests/test_e2e_config.yaml` | `test_backfill_e2e.py` |

```yaml
# Email address only — password is fetched from the vault
email: "yourtest@gmail.com"
```

This lets you use different accounts for integration vs E2E tests, or the same account in both.

### 3. Run the test suites

```bash
# Integration tests (unit-level sync, client, send/reply/forward, drafts, search, etc.)
uv run pytest external_data_ingestion/tests/test_integration.py -v -s

# End-to-end backfill + integrity verification (fresh DB, full sync flow, IMAP comparison)
uv run pytest external_data_ingestion/tests/test_backfill_e2e.py -v -s
```

Or pass the email address via CLI (overrides the config file):

```bash
uv run pytest external_data_ingestion/tests/test_integration.py -v -s \
  --email "you@gmail.com"

uv run pytest external_data_ingestion/tests/test_backfill_e2e.py -v -s \
  --email "you@gmail.com"
```

Tests set `INTENTFRAME_EMAIL_HOME` to a temp directory and fetch passwords from the vault — same code path as production, no special credential injection.

### Test coverage

| Area | Tests | File |
|---|---|---|
| Providers / Config | 5 | test_integration.py |
| DB Schema | 4 | test_integration.py |
| Folder Discovery | 2 | test_integration.py |
| Sync (full, incremental, state, headers_raw) | 5 | test_integration.py |
| Send / Delivery / Reply / Forward | 6 | test_integration.py |
| Drafts | 2 | test_integration.py |
| Flags (read/unread) | 2 | test_integration.py |
| Client reads (folders with roles, headers_only, message counts) | 10 | test_integration.py |
| Search (FTS) | 2 | test_integration.py |
| Thread reconstruction | 1 | test_integration.py |
| Client writes | 2 | test_integration.py |
| Event observer | 2 | test_integration.py |
| Move email | 2 | test_integration.py |
| Delete email | 1 | test_integration.py |
| Daemon lifecycle + folder persistence | 7 | test_integration.py |
| Multi-account storage isolation | 3 | test_integration.py |
| Account management | 6 | test_integration.py |
| Tiered sync (schema, headers-only, body upgrade, lazy fetch, metadata-only attachments) | 8 | test_integration.py |
| Summary | 2 | test_integration.py |
| Backfill E2E (priority-first flow, fresh DB, attachments, IMAP UID integrity) | 15 | test_backfill_e2e.py |
| **Total** | **86** |

## Project structure

```
external_data_ingestion/
├── pyproject.toml                 # package definition, dependencies, scripts
├── README.md
├── external_data_ingestion/
│   └── email/
│       ├── __main__.py            # CLI entry point
│       ├── daemon.py              # SyncDaemon controller + run_daemon()
│       ├── sync.py                # sync_folder, sync_all_folders, upgrade_folder_bodies, run_idle, verify_integrity
│       ├── imap_connection.py      # ConnectionProvider (pool, semaphore, retry), FolderCache, force_close
│       ├── client.py              # EmailClient (async reads + writes)
│       ├── actions.py             # IMAP/SMTP write operations
│       ├── config.py              # Config loading, account management, workspace resolution
│       ├── db.py                  # SQLite schema init, event logging
│       ├── folders.py             # RFC 6154 folder discovery
│       ├── models.py              # Pydantic models
│       ├── providers.py           # IMAP/SMTP host auto-detection
│       └── threading_utils.py     # Email thread reconstruction
└── tests/
    ├── conftest.py                # Shared fixtures, cleanup
    ├── test_config.yaml           # Integration test credentials (gitignored)
    ├── test_e2e_config.yaml       # E2E test credentials (gitignored)
    ├── test_integration.py        # Full integration test suite
    └── test_backfill_e2e.py       # End-to-end backfill + IMAP integrity verification
```

## Key design decisions

- **IMAP connection budget** — every connection goes through `ConnectionProvider` (one per account, in `imap_connection.py`), which enforces a concurrency cap (default max 3 via semaphore), maintains an idle connection pool with NOOP health checks, and retries login failures ("Too many simultaneous connections") with exponential backoff. Connections are borrowed via `async with provider.connection() as mb:` — the context manager guarantees cleanup on error (logout + raw `socket.shutdown(SHUT_RDWR)` to prevent zombie TCP connections). Every socket has TCP keepalive enabled (60s idle, 10s probe interval, 3 probes) so dead connections are detected within ~90 seconds instead of waiting 10–30 minutes for the server-side timeout. Multi-folder operations (`sync_all_folders`, `upgrade_all_folders_bodies`, `verify_integrity`) open one connection and reuse it across all folders. The priority sync shares a single connection for folder discovery, INBOX, and Sent. See [`concepts/imap_connection_budget.md`](external_data_ingestion/concepts/imap_connection_budget.md) for the full design.
- **Network recovery** — when the network drops (lid closed, sleep, Wi‑Fi), TCP keepalive detects the dead connection within ~90 seconds and tears down the socket, freeing Gmail's server-side slot. IDLE reconnects with exponential backoff (30s → 300s max) and retries indefinitely. The IDLE connection is proactively cycled every ~25 minutes to prevent Gmail's ~29-minute server-side timeout. Periodic sync retries every 5 minutes. Backfill does not retry on failure; restart the daemon to re-run it. New messages are always picked up within 5 minutes of network recovery. See [`concepts/network_recovery_and_concurrent_tasks.md`](external_data_ingestion/concepts/network_recovery_and_concurrent_tasks.md) for details.
- **Priority-first sync** — initial sync fetches full content (headers + bodies) for INBOX and Sent using an IMAP `SINCE` filter (default 90 days), making the system usable within minutes. A background backfill task then syncs old INBOX + Sent headers and remaining folders. `[Gmail]/All Mail` is skipped entirely (redundant). Older bodies and all attachment payloads are fetched on-demand by `EmailClient` and persisted locally so they're never re-downloaded. Each email row tracks its content level (`content_level`: 0 = headers-only, 1 = body fetched).
- **Staggered background tasks** — IDLE starts immediately for real-time notifications. Backfill runs next. Periodic sync is deferred until backfill completes (via `asyncio.Event`) to avoid redundant overlapping work and connection contention. **Sent** is not covered by IDLE; outbound copies appear in local SQLite after IMAP sync of the Sent folder (see [Outbound mail, Sent folder, and local search latency](#outbound-mail-sent-folder-and-local-search-latency) above).
- **Automatic integrity verification** — after backfill completes and after every periodic sync, the daemon compares local UIDs against the IMAP server via `verify_integrity()`. Gmail exposes the same message in multiple IMAP folders (labels), so the check fetches Message-ID headers for candidate "missing" UIDs and cross-references against all local message_ids — UIDs stored under a different mailbox are reported as `cross_folder` (not gaps). Only truly absent messages are flagged. Gaps are logged as warnings and recorded as `integrity_check` events in the DB. The same function powers the `email-sync-daemon verify` CLI command.
- **Folder discovery cache** — folder lists are cached per-account with a 5-minute TTL in `imap_connection.FolderCache`. Discovery, backfill, sync, and integrity checks all read from the cache, eliminating redundant IMAP `LIST` commands.
- **Single workspace root** — config, db, and attachments all derive from one path (`~/.intentframe/email`). Override once with `INTENTFRAME_EMAIL_HOME` and everything follows.
- **Zero-config client** — `EmailClient()` takes no arguments. Consumers pass email addresses, nothing else. The client reads from the daemon's workspace internally. On-demand IMAP fetches for bodies and attachments are transparent to the caller.
- **Multi-account safe** — emails are uniquely identified by `(account_email, message_id)`. The same message delivered to two accounts is stored separately with independent flags, folders, and sync state.
- **imap-tools** for IMAP operations — mature, well-tested synchronous library. Called via `asyncio.to_thread()` for all operations.
- **IDLE socket kill** for shutdown — `SyncDaemon.request_stop()` calls `force_close()` on live IDLE connections and `provider.force_disconnect_all()` on each account's pool, instantly unblocking any thread stuck in `idle.wait()` and marking providers as closed so returning connections are destroyed rather than recycled. No zombie threads, no 300-second hangs.
- **RFC 6154 folder roles** — the server tells us which folder is Drafts/Sent/Trash via special-use flags. No hardcoded folder names (they're locale-dependent). Discovered folders are persisted in a `folders` table (schema v3) so external consumers can query roles without live IMAP access.
- **SQLite WAL mode** — allows the daemon to write while the client reads concurrently without locking.
- **FTS5** — full-text search on subject, sender, and body fields. FTS index is updated via triggers on INSERT, UPDATE, and DELETE — body text becomes searchable after body upgrade or lazy fetch.
