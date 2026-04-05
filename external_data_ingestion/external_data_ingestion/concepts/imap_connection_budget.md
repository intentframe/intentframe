# IMAP connection budget and reuse

## Problem

Gmail enforces a limit of 15 simultaneous IMAP connections per account. The original daemon architecture opened a fresh IMAP connection for every individual operation — each `sync_folder` call, each `discover_folders` call, each IDLE loop iteration, each integrity check. Under normal operation a single account could easily create 4+ overlapping connections at startup, and a burst of connections during backfill could exceed the limit entirely, producing:

```
[ALERT] Too many simultaneous connections. (Failure)
```

This was treated as a fatal error, crashing the affected task.

### Connection count before the change

| Phase | Connections | Lifetime |
|---|---|---|
| Priority sync: discover folders | 1 | short |
| Priority sync: INBOX | 1 | short |
| Priority sync: Sent | 1 | short |
| IDLE loop | 1 | persistent |
| Periodic sync (per folder) | 1 each | short |
| Backfill: discover folders | 1 | short |
| Backfill: headers per folder | 1 each | short |
| Backfill: bodies per folder | 1 each | short |
| Backfill: verify integrity | 1+ | short |

Total logins during a full startup + backfill cycle for one account with 10 folders: **~30 login/logout cycles**, with up to 4 concurrent at peak (IDLE + backfill folder sync + periodic sync + integrity check all running simultaneously).

## Solution

All IMAP connection management is centralised in `imap_connection.py` through a `ConnectionProvider` class — one instance per account, obtained via `get_provider(account)`. No other module creates `MailBox` objects or calls `login()` directly.

### 1. ConnectionProvider: per-account connection pool

```python
# imap_connection.py
provider = get_provider(account)

async with provider.connection() as mb:
    mb.folder.set("INBOX")
    messages = list(mb.fetch(...))
```

Every IMAP connection is borrowed through `provider.connection()`, an async context manager that:

1. **Acquires** a semaphore permit (blocks if `max_conns` are already out)
2. **Pops** an idle connection from the pool, or creates a new one (with retry)
3. **Health-checks** idle connections via `NOOP` before returning them
4. **Yields** the `MailBox` for use
5. **On normal exit**: returns the connection to the idle pool (or destroys it if the pool is full / provider is closed)
6. **On error**: forcefully closes the socket via `socket.shutdown(SHUT_RDWR)` + `socket.close()` — no zombie TCP connections
7. **Releases** the semaphore permit in every case

The semaphore is per-account, not global — two different email accounts can each have up to 3 concurrent connections independently.

Why 3 and not 1: the daemon runs IDLE (persistent, 1 connection), and needs at least 1 more for sync/backfill work. A budget of 3 allows IDLE + one sync operation + one integrity check to coexist without blocking each other.

### 2. Connection reuse within multi-folder operations

Functions that iterate over multiple folders open **one** connection and pass it through:

| Function | Before | After |
|---|---|---|
| `sync_all_folders()` | 1 connection per folder | 1 connection total, folder.set() per folder |
| `upgrade_all_folders_bodies()` | 1 connection per folder | 1 connection total |
| `verify_integrity()` | 2–3 connections (discover + UIDs + message-IDs) | 1 connection total |
| `SyncDaemon.start()` priority pass | 3 connections (discover + INBOX + Sent) | 1 connection total |

`sync_folder()` and `upgrade_folder_bodies()` require an `mb: MailBox` parameter (keyword-only, no default). The caller owns the connection — these functions call `mb.folder.set(name)` but never close it.

### 3. Idle connection pool with health checks

`ConnectionProvider` maintains an `asyncio.Queue` of idle `MailBox` instances (max size = `max_conns`). When `connection()` is called:

1. Try to pop from the idle queue
2. Run `NOOP` on the connection to verify it's still alive
3. If healthy, return it (no login required)
4. If unhealthy, destroy it (logout + force_close) and try the next
5. If queue is empty, create a new connection via `asyncio.to_thread`

On normal exit from the context manager, the connection is returned to the idle queue. If the queue is full or the provider is closed, it's destroyed instead.

### 4. Folder discovery cache

```python
# imap_connection.py
folders = await get_or_discover_folders(mb, account.email)
```

The first call to `get_or_discover_folders` for an account issues the IMAP `LIST` command and caches the result in a module-level `FolderCache` (TTL = 300 seconds). Subsequent calls within the 5-minute window return a shallow copy. This eliminates redundant folder discovery across priority sync, backfill, periodic sync, and integrity checks.

The cache is keyed by email address and uses `time.monotonic()` for the TTL clock.

### 5. TCP keepalive on every connection

Every IMAP socket has TCP keepalive enabled immediately after login:

```python
# imap_connection.py → _enable_keepalive()
sock.setsockopt(SOL_SOCKET, SO_KEEPALIVE, 1)
# Linux:  TCP_KEEPIDLE=60, TCP_KEEPINTVL=10, TCP_KEEPCNT=3
# macOS:  TCP_KEEPALIVE=60
```

Without keepalive, a network drop (lid close, Wi-Fi loss) leaves "zombie" TCP connections that Gmail still counts against the 15-connection limit for 10–30 minutes (until Gmail's own server-side timeout fires). With keepalive, the OS probes the dead connection after 60 seconds of silence, retries 3 times at 10-second intervals, and tears down the socket within ~90 seconds — freeing the server-side slot.

This is critical for the IDLE connection (held for minutes/hours) and directly addresses the "Too many simultaneous connections" errors that occurred after network disruptions.

### 6. Proactive IDLE cycling

```python
# sync.py → run_idle()
IDLE_WAIT = 5 * 60          # 5 min per idle.wait() call
IDLE_CYCLE_AFTER = 25 * 60  # reconnect after 25 min on same connection
```

Instead of holding one IDLE connection indefinitely, `run_idle` exits and re-enters `provider.connection()` every ~25 minutes. This mirrors Apple Mail (~28 min) and Thunderbird's IDLE cycling. The benefits:

1. **Detects silently-dead connections** — if the connection died without an RST (e.g. NAT timeout), the health check on re-acquisition fails and a fresh connection is created
2. **Prevents server-side IDLE timeout** — Gmail drops IDLE connections after ~29 minutes; cycling at 25 minutes avoids hitting that limit
3. **Frees server-side resources** — the old connection is properly closed before a new one is opened, preventing accumulation of stale server-side state

Each individual `idle.wait()` call blocks for 5 minutes. After ~5 iterations (~25 min total), the inner loop breaks, the context manager returns the connection, and the outer loop re-acquires (with a NOOP health check on the pooled connection or a fresh login).

### 7. Exponential backoff on connection-limit errors

```python
# imap_connection.py → ConnectionProvider._create_sync()
for attempt in range(4):
    mb = MailBox(host, port)
    try:
        mb.login(email, password)
        return mb
    except Exception as exc:
        force_close(mb)  # raw socket shutdown — no zombies
        if "Too many simultaneous connections" in str(exc):
            sleep(min(5 * 2**attempt, 60))  # 5s, 10s, 20s, 40s
            continue
        raise
```

Instead of crashing, the connection attempt retries up to 4 times with delays of 5, 10, 20, and 40 seconds (capped at 60). The failed `MailBox` is forcefully closed at the socket level (`socket.shutdown(SHUT_RDWR)` + `socket.close()`) before retrying to prevent zombie TCP connections that Gmail would still count against the limit.

### 8. Staggered background task startup

```
daemon.py → SyncDaemon.start()

1. Priority sync (blocking, sequential)
2. Spawn IDLE           ← starts immediately
3. Spawn Backfill       ← starts immediately, sets backfill_done Event on completion
4. Spawn Periodic Sync  ← waits for backfill_done before entering its loop
```

Before: IDLE, periodic sync, and backfill all started simultaneously, creating a burst of 3+ new connections immediately after priority sync.

After: periodic sync is wrapped in `_deferred_periodic_sync()` which races `backfill_done` against `stop_event` using `asyncio.wait(return_when=FIRST_COMPLETED)` with a 1-hour timeout. This ensures the task unblocks immediately on shutdown rather than waiting up to an hour. Since backfill already syncs every folder, running periodic sync in parallel would be redundant and wasteful. Once backfill completes, periodic sync takes over.

### 9. Shutdown: force-close all connections

```python
# daemon.py → SyncDaemon.request_stop()
self._stop.set()
for mb in list(self._idle_connections):
    force_close(mb)                           # kill live IDLE sockets
self._idle_connections.clear()
for account in self._config.accounts:
    get_provider(account).force_disconnect_all()  # drain idle pools + mark closed
```

`force_disconnect_all()` marks the provider as closed (so returning connections are destroyed rather than recycled) and drains every idle socket from the pool via `force_close()`. Active connections fail on their next I/O, and the `connection()` context manager handles the resulting exception by destroying the connection.

## Connection count after the change

| Phase | Connections | Lifetime |
|---|---|---|
| Priority sync (discover + INBOX + Sent) | **1** | short (returned to pool) |
| IDLE loop | 1 | persistent |
| Backfill: discover + INBOX + Sent old headers | **1** | short (may reuse from pool) |
| Backfill: all other headers (`sync_all_folders`) | **1** | short (may reuse from pool) |
| Backfill: all other bodies (`upgrade_all_folders_bodies`) | **1** | short (may reuse from pool) |
| Backfill: verify integrity | **1** | short (may reuse from pool) |
| Periodic sync (`sync_all_folders`) | **1** | short (may reuse from pool) |
| Periodic verify integrity | **1** | short (may reuse from pool) |

Total logins for same startup + backfill cycle: **as few as 2** (one for IDLE, one for everything else via pool reuse — down from ~30). Peak concurrent: **2** (IDLE + one backfill/sync operation). The semaphore guarantees the peak never exceeds 3.

## Cross-process connection budget

The per-account semaphore is scoped to a single Python event loop via `get_provider()` (keyed by `id(asyncio.get_running_loop())`). This means **the concurrency cap only applies within one OS process**. Different processes get independent providers with independent semaphores.

### Daemon alone (single process)

The daemon's observed peak is **2** concurrent connections (IDLE + one sync/backfill op), not 3, because the task structure serialises work:

- Periodic sync waits for backfill to complete (`_deferred_periodic_sync`)
- Backfill phases run sequentially within a single `provider.connection()`
- Integrity checks run after sync, not alongside it

The semaphore allows 3, but the staggered design means the 3rd permit is only used if an `actions.py` write (e.g., `move_email` triggered by a user) overlaps with IDLE + sync.

### Daemon + EmailClient in a separate process

`EmailClient` can be consumed by an external service in a separate process (FastAPI, worker, etc.). That process has its own event loop and therefore its own `ConnectionProvider` with its own `Semaphore(3)`.

If the daemon is at peak (2 connections) and the external consumer simultaneously triggers a lazy body fetch or attachment download, Gmail sees **3 total** — well within the 15-connection limit.

In practice, `EmailClient` opens IMAP connections only for:

| Operation | When | Duration |
|---|---|---|
| Lazy body fetch (`get_email` on `content_level=0` row) | First time a headers-only message is read with full body requested | Sub-second |
| Lazy attachment download (`download_attachment`) | First time an attachment payload is requested | Sub-second |
| Write actions (move, delete, flag, draft) | User-initiated, infrequent | Sub-second |

These are brief, infrequent, and never concurrent with each other in normal usage. The realistic cross-process peak is **daemon 2 + client 1 = 3 total**.

### Daemon + EmailClient + external mail clients

Gmail's 15-connection limit is per-account at the server, shared across all IMAP clients:

| Client | Typical connections | Lifetime |
|---|---|---|
| Our daemon | 2 (IDLE + sync) | 1 persistent + 1 short |
| Our EmailClient (external consumer) | 0–1 | Sub-second bursts |
| Apple Mail (macOS) | 1 per folder (~5–10) | Persistent |
| iPhone Mail | 1–3 | Persistent |
| Thunderbird | 1–5 | Persistent |

Worst case (daemon + external consumer + Apple Mail + iPhone): 2 + 1 + 8 + 3 = **14** — right at the edge. If it exceeds 15, the daemon's exponential backoff (5s, 10s, 20s, 40s) retries gracefully. Failed login attempts force-close the raw socket immediately so Gmail doesn't count zombie connections against the limit.

## Module layout

```
email/
├── imap_connection.py  ← ConnectionProvider (pool, semaphore, retry, health check),
│                         FolderCache, get_or_discover_folders, force_close, get_provider
├── sync.py             ← sync_folder (mb= required), sync_all_folders, verify_integrity
│                         (all connections obtained via provider.connection())
├── daemon.py           ← SyncDaemon.start (reuse), _backfill_account,
│                         _deferred_periodic_sync (stagger), request_stop (force_disconnect_all)
├── actions.py          ← send, draft, flag, move, delete (all via provider.connection())
└── client.py           ← on-demand body/attachment fetch (all via provider.connection())
```

All write operations in `actions.py` and on-demand fetches in `client.py` also go through `provider.connection()`. No code path bypasses the connection provider.

## Test changes

Tests previously opened their own IMAP connections inside each test method to discover folders. A session-scoped `discovered_folders` fixture in `conftest.py` now discovers folders once per test session via the provider and shares the result:

```python
@pytest_asyncio.fixture(scope="session")
async def discovered_folders(account):
    from external_data_ingestion.email.imap_connection import get_provider

    provider = get_provider(account)
    async with provider.connection() as mb:
        folders = await discover_folders(mb)
    return folders
```

All test methods that call `sync_folder` or `upgrade_folder_bodies` obtain their connections via `get_provider(account).connection()` and pass the `MailBox` as the required `mb=` argument. This ensures tests exercise the exact same connection lifecycle as production.

## Invariants

1. Every IMAP connection is obtained via `provider.connection()` — an async context manager that guarantees semaphore release and socket cleanup in all code paths.
2. When `mb` is passed to `sync_folder` / `upgrade_folder_bodies`, the caller owns the connection — those functions must not close it.
3. `sync_folder` and `upgrade_folder_bodies` require `mb` as a keyword-only argument (no default) — standalone mode was removed to eliminate bypass paths.
4. The semaphore count is tracked manually via `_permits_out` — no reliance on private `asyncio.Semaphore` internals.
5. `ConnectionProvider._create_sync()` calls `force_close(mb)` on every login failure, preventing zombie TCP sockets.
6. Every successful login calls `_enable_keepalive()` — dead connections are detected within ~90 seconds instead of 10–30 minutes.
7. IDLE cycles every ~25 minutes (`IDLE_CYCLE_AFTER`) — prevents Gmail's 29-minute IDLE timeout from killing the connection unexpectedly.
8. `FolderCache.get()` returns a shallow copy — callers can filter/mutate the list without corrupting the cache.
9. Providers are scoped to `(event_loop_id, email)` via `asyncio.get_running_loop()` — multiple event loops in the same process each get independent providers.
10. `_deferred_periodic_sync` races `backfill_done` against `stop_event` — shutdown unblocks the wait immediately.
11. `force_disconnect_all()` marks the provider as closed (`_closed = True`) so connections returned after shutdown are destroyed, not recycled.
