# Email Sync (EDI)

> IntentFrame's dedicated email service — a local IMAP IDLE + SMTP daemon backed by SQLite, plus a typed Python client used by the executor and Jarvis.

EDI ("External Data Ingestion") is the only place in IntentFrame that talks IMAP or SMTP. The executor's `MailAdapter` and Jarvis's email tools both go through EDI's client; nothing else opens an IMAP connection. This means email credentials live in exactly one place (the vault), connection budgets are managed centrally, and every email read or write goes through the same audited path.

For implementation details (full daemon design, connection pooling internals, full client API), see [`../external_data_ingestion/README.md`](../external_data_ingestion/README.md).

---

## Why a dedicated email service

There are four reasons email is its own daemon instead of an inline executor adapter.

**1. IMAP IDLE wants a long-lived connection.** Real-time INBOX updates require the daemon to hold an IMAP IDLE socket open for the lifetime of the user's session. The executor is request-driven; it has no place to hold long-lived state.

**2. Connection budgets are global.** Gmail caps at ~15 concurrent IMAP connections per account. Outlook is similar. If every adapter, agent, or test opened its own IMAP connection, the user would hit the cap during normal use. EDI's `ConnectionProvider` enforces a per-account semaphore (default 3) and pools healthy connections across all callers, so the budget stays under control.

**3. Local SQLite is the right read store.** Email reads — list, search, get-by-thread — are dominated by client-side queries. Hitting IMAP for every read would be catastrophic for latency and connection count. EDI maintains a local SQLite mirror with FTS5 full-text search; reads are sub-millisecond and don't touch the network.

**4. Credential isolation.** IMAP and SMTP passwords are sensitive. EDI is the only process that holds them, and it gets them from the credentials vault as `executor_only` (in-memory `SecretStr`) — never via env var, never on disk in plaintext.

---

## What EDI actually does

```
┌──────────────────────────────────────────────────────────────────┐
│                  EDI DAEMON (process)                             │
│                  external_data_ingestion/                         │
│                                                                   │
│  Per account:                                                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ ConnectionProvider                                         │ │
│  │  • Semaphore(3) — concurrent connection cap               │ │
│  │  • Pool of idle connections (healthy NOOP-checked)         │ │
│  │  • FolderCache (5-min TTL)                                 │ │
│  │  • Exponential backoff on connection-limit errors          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Workflow:                                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 1. Priority sync: discover folders → INBOX → Sent          │ │
│  │ 2. IDLE loop on INBOX (immediate notifications)             │ │
│  │ 3. Background backfill: remaining folders, headers + bodies │ │
│  │ 4. Periodic re-sync (5-min after backfill)                 │ │
│  │ 5. Integrity verification: local UIDs vs server UIDs        │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Storage:                                                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ ~/.intentframe/email/<account>/email.db                    │ │
│  │   SQLite + WAL + FTS5                                      │ │
│  │   schema: messages, threads, folders, attachments_meta     │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ direct read (sub-ms) for queries
                              │ on-demand IMAP fetch for full bodies & attachments
                              │
              ┌───────────────┼─────────────────────────┐
              │               │                         │
       ┌──────▼──────┐ ┌──────▼──────┐         ┌────────▼─────────┐
       │ Executor    │ │  Jarvis     │         │  External        │
       │  MailAdapter│ │  email tools│         │  consumers       │
       │             │ │             │         │  (notebooks, etc)│
       └─────────────┘ └─────────────┘         └──────────────────┘
                              ▲
                              │
                              │ EmailClient() — zero-arg, reads from
                              │ shared SQLite, writes via IMAP/SMTP
                              │ through the same ConnectionProvider
```

### What lives where

| Data | Where | Encryption |
|---|---|---|
| Email headers + bodies | `~/.intentframe/email/<account>/email.db` (SQLite) | Plaintext on disk; rely on FileVault / disk encryption |
| Attachment payloads | Fetched on-demand from IMAP, not stored | n/a |
| IMAP/SMTP password | macOS Keychain via the credentials vault | Encrypted (AES-256 on macOS) |
| Daemon PID / sockets | `~/.intentframe/run/email-sync-daemon.*` | n/a |

---

## How the executor uses EDI

The executor's `MailAdapter` (Python) is a thin wrapper around `EmailClient` from `external_data_ingestion.client`.

```python
from external_data_ingestion.client import EmailClient

client = EmailClient()  # zero-arg — reads accounts from config

# READ: hits SQLite (sub-ms)
messages = client.list("you@gmail.com", folder="INBOX", limit=50)

# READ: lazy body fetch — hits IMAP only if body wasn't synced
full_msg = client.get_email(message_id, headers_only=False)

# WRITE: goes through the shared ConnectionProvider for SMTP
client.send(
    from_address="you@gmail.com",
    to=["someone@example.com"],
    subject="...",
    body="...",
)
```

When the executor receives a `READ_EMAIL` or `SEND_EMAIL` intent (after the pipeline approves it), the `MailAdapter` calls into `EmailClient`. The client either reads SQLite directly or borrows a connection from `ConnectionProvider` — without the executor ever touching IMAP itself.

---

## How Jarvis uses EDI

Jarvis (the reference agent in `jarvis_pa/`) is a *consumer*, not an adapter. It uses the same `EmailClient`:

```python
from external_data_ingestion.client import EmailClient

email = EmailClient()
recent = email.list("you@gmail.com", folder="INBOX", limit=20)
unread_count = email.count("you@gmail.com", folder="INBOX", unread=True)
```

Jarvis exposes these as LLM-callable tools (`list_emails`, `get_email`, `send_email`, …). When the LLM decides to send an email, it goes through `actor.submit({"action": "SEND_EMAIL", ...})` → IntentFrame pipeline → executor's `MailAdapter` → `EmailClient` → SMTP. The same `EmailClient` is used for both the agent's read tools (which don't need pipeline gating because they're read-only and bound to the user's own data) and the eventual send (which does, via the executor).

---

## Cross-process connection budget

There are usually three things using EmailClient at once: the daemon's own sync loops, the executor's `MailAdapter`, and Jarvis's tools. Each of them is in a different OS process. The connection budget needs to stay under Gmail/Outlook's limit *across all of them*.

EDI handles this with a two-layer pool model:

- **Within one process**, all consumers share one `ConnectionProvider` instance. The semaphore enforces the local cap.
- **Across processes**, each process gets its own `ConnectionProvider` (because they don't share Python state). The total cap is `n_processes × semaphore_size` — typically 3 + 3 + 3 = 9 connections, well under Gmail's 15-conn limit.

For the deep design rationale, see [`../external_data_ingestion/external_data_ingestion/concepts/imap_connection_budget.md`](../external_data_ingestion/external_data_ingestion/concepts/imap_connection_budget.md).

---

## Outbound traffic profile

EDI is the only process in IntentFrame that talks IMAP or SMTP. From [privacy.md § Outbound traffic](privacy.md#outbound-traffic), EDI's network footprint is:

| Direction | Endpoint | Frequency | Payload |
|---|---|---|---|
| Outbound IMAP | Your provider's IMAP server (e.g. `imap.gmail.com:993`) | Continuous (IDLE loop) + periodic sync (5-min) | IMAP commands and message data over TLS |
| Outbound SMTP | Your provider's SMTP server (e.g. `smtp.gmail.com:587`) | Per `send` / `reply` / `forward` call | SMTP commands and outgoing message over TLS |

No third party gets this traffic. It goes directly to the provider you configured. There is no intermediate "IntentFrame email service" or analytics endpoint.

---

## Setup checklist

1. **Vault is running.** EDI hard-fails at startup if the credential vault isn't reachable.
2. **Email password is in the vault.** Namespace `email.<address>`, key `password`. For Gmail, use an [App Password](https://myaccount.google.com/apppasswords) (requires 2FA).
3. **Account is registered.** `uv run email-sync-daemon add you@gmail.com` (the daemon validates IMAP login during registration; password comes from the vault, not a CLI argument).
4. **Daemon is running.** Started by the gateway in Step 7. Independent of the rest of the platform — even if the executor is down, EDI keeps syncing email so it's fresh when the agent starts.

For full setup steps including provider auto-detection and custom IMAP settings, see [`../external_data_ingestion/README.md`](../external_data_ingestion/README.md).

---

## Quick answers

| Question | Answer |
|---|---|
| Where is my email stored? | `~/.intentframe/email/<account>/email.db` — local SQLite. |
| Where is my password stored? | macOS Keychain via the credentials vault. Never in `config.yaml`, never in env vars. |
| Does IntentFrame send my emails to anyone? | Only to your IMAP provider for sync, and your SMTP provider when you (or your agent) sends one. No third party. |
| Does the agent see my password? | No. EDI is the only process with the password. The agent talks to `EmailClient`, which talks to the daemon / SMTP. |
| What if the daemon is down? | Reads from the local SQLite still work. Writes (send / reply) fail with a connection error. |
| What if I'm offline? | Reads from SQLite work. The daemon will reconnect and resync when the network comes back. The integrity verifier reconciles UIDs after each reconnect. |
| Is search private? | Yes — FTS5 runs locally on the SQLite mirror. Nothing leaves your machine for search. |
| Can I delete the local mirror? | Yes — delete `~/.intentframe/email/<account>/email.db`. The daemon will rebuild it on next sync. |
| Does this work with Outlook / iCloud / Yahoo? | Yes — provider settings auto-detect by domain. Custom IMAP works too (set `imap_host`, `smtp_host` in `config.yaml`). |
| Why not just use the macOS Mail.app bridge? | Latency (AppleScript is slow), reliability (Mail.app may not be running), and portability (EDI works on Linux too, Mail.app doesn't). The platform server's Mail service is retained for niche Mail.app-specific operations. |

---

## Limitations

- **No outbound attachments yet.** `send`, `reply`, `forward`, `create_draft` send plain or HTML body only. Attaching files isn't implemented.
- **`[Gmail]/All Mail` is skipped during backfill.** It's redundant with the individual folder syncs.
- **Local mirror is plaintext on disk.** Use FileVault / LUKS for at-rest protection.
- **No multi-instance arbitration.** Two EDI daemons for the same account on the same machine would race on connection budget. The supervisor ensures only one runs.

---

## Related documents

- [`../external_data_ingestion/README.md`](../external_data_ingestion/README.md) — Implementation reference: full daemon design, complete client API, configuration, attachment handling
- [`../external_data_ingestion/external_data_ingestion/concepts/imap_connection_budget.md`](../external_data_ingestion/external_data_ingestion/concepts/imap_connection_budget.md) — Connection pool design and cross-process budget rationale
- [credentials-vault.md](credentials-vault.md) — How EDI fetches IMAP/SMTP passwords
- [processes.md](processes.md) — Where EDI sits in the process tree
- [privacy.md](privacy.md) — EDI's outbound traffic catalog and on-disk footprint
- [macos-platform-server.md](macos-platform-server.md) — Why the executor uses EDI instead of the platform server's Mail service
