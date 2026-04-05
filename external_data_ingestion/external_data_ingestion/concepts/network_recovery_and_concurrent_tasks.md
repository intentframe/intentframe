# Network recovery and concurrent task behavior

Findings from production runs and analysis of how the daemon behaves when the network drops (e.g. MacBook lid closed, sleep, Wi‑Fi disconnect) and how the three concurrent tasks interact.

## Concurrent tasks per account

| Task | Purpose | Connection pattern |
|------|---------|--------------------|
| **IDLE** | Real-time INBOX notifications via IMAP IDLE | Persistent connection via `provider.connection()`, reconnects on error |
| **Backfill** | One-shot: old headers, all folders, body upgrade, integrity | Borrows connections from `ConnectionProvider` pool per phase |
| **Periodic sync** | Every 5 min: incremental sync all folders + integrity | Borrows connection from pool per cycle |

## Network drop: what happens to each task

### IDLE

- **Error**: `socket error: EOF` or `BrokenPipeError` when the TCP connection dies (server closed it or network dropped).
- **Behavior**: The `provider.connection()` context manager destroys the dead connection (logout + `force_close`), releases the semaphore permit. The outer `run_idle` loop logs `idle_error`, waits backoff (30s → 60s → 120s → 240s, max 300s), then re-enters `provider.connection()` which creates or reuses a fresh connection. Logs `idle_reconnected` on success.
- **TCP keepalive**: Every IMAP socket has keepalive enabled (60s idle, 10s interval, 3 probes). If the network drops silently, the OS tears down the socket within ~90s — preventing zombie connections that Gmail still counts against the 15-connection limit.
- **Proactive cycling**: Even without errors, the IDLE connection is recycled every ~25 minutes (each `idle.wait()` blocks for 5 min, after ~5 iterations the connection is returned and re-acquired with a health check). This prevents Gmail's ~29-minute IDLE timeout from unexpectedly killing the connection.
- **Retries**: **Forever** — only stops on daemon shutdown (`stop_event`). No upper limit on retries.
- **Recovery**: New messages are picked up as soon as IDLE reconnects and receives a wakeup (or on the next 5‑minute IDLE wait cycle).

### Backfill

- **Error**: Any exception (including socket EOF) during steps 1–4.
- **Behavior**: Logs `backfill_error`, sets `backfill_done`, exits. **No retry** within the same daemon run.
- **Recovery**: Whatever was synced before the crash is persisted. Remaining steps (folders not yet synced, body upgrade, integrity) are skipped until the daemon is restarted (which triggers a fresh backfill).

### Periodic sync

- **Error**: Logs `periodic_sync_error` or `periodic_integrity_error`.
- **Behavior**: Waits 5 minutes, then runs the next cycle. **Retries every cycle**.
- **Recovery**: Fully self-healing. New messages are synced on the next successful cycle.

## Getting latest messages when network reconnects

| Scenario | How new messages are synced |
|----------|-----------------------------|
| Network drops, then comes back | **IDLE** reconnects (within 5 min max backoff) and listens for new mail. TCP keepalive ensures zombie connections are torn down in ~90s, freeing server-side slots for reconnection. **Periodic sync** also runs every 5 min and syncs all folders incrementally. |
| IDLE still in backoff | Periodic sync still runs and catches new messages within 5 minutes. |
| Backfill crashed mid-run | New messages: **yes** — IDLE and periodic sync both handle them. Old messages in folders backfill hadn’t reached: **no** — only after daemon restart (fresh backfill). |

**Bottom line**: New messages are always picked up within 5 minutes of network recovery, either by IDLE or periodic sync. Old historical messages in folders that backfill never reached are only synced after a daemon restart.

## IDLE retry behavior

- **Retries indefinitely** until shutdown.
- **Backoff**: 30s, 60s, 120s, 240s, max 300s (capped).
- **Proactive cycle**: every ~25 min the connection is returned to the pool and re-acquired (health-checked via NOOP), even without errors. Logs `idle_cycle` with `held_seconds`.
- **Log**: `idle_reconnected` when a successful reconnection happens after a previous error.

## Common causes of IDLE errors

| Cause | Typical error |
|-------|----------------|
| MacBook lid closed / sleep | `socket error: EOF`, `BrokenPipeError` |
| Gmail IDLE timeout (~29 min) | `socket error: EOF` (prevented by 25-min proactive cycle) |
| Wi‑Fi disconnect | `socket error: EOF` (detected within ~90s via TCP keepalive) |
| Router/ISP dropping long-lived connections | `socket error: EOF` |

These are expected. TCP keepalive detects silent network drops within ~90 seconds. Proactive IDLE cycling prevents Gmail's 29-minute server-side timeout from being reached. In all cases, the daemon reconnects automatically with backoff.

## Config hot-reload

**Adding a new account while the daemon is running**: The daemon ignores it. Config is loaded once at startup. Restart the daemon to pick up new accounts.

## Related docs

- [production_behavior_and_limitations.md](./production_behavior_and_limitations.md) — daemon lifecycle, persistence, known limitations
- [imap_connection_budget.md](./imap_connection_budget.md) — connection reuse, semaphore, folder cache
