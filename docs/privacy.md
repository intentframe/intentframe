# Data, Privacy, and Outbound Traffic

> What IntentFrame stores on your machine, where it stores it, what leaves the machine, and from which process.

This document answers the questions a security-conscious user actually asks before installing IntentFrame: *where does my data live, who has access to it, and what gets sent off-machine?*

For the process model that this document references, see [processes.md](processes.md).

---

## Summary in one paragraph

IntentFrame is local-first. All policy data, audit logs, runtime state, agent memory, and email mirrors live on your machine, under `~/.intentframe/`. The only IntentFrame-internal traffic that leaves your machine is **OpenAI API calls** (from `intentframe-server` for the Analysis Engine and Guardian, and from `jarvis` for the agent's own reasoning). The **email sync daemon (EDI)** also talks to your configured email provider over IMAP/SMTP. Everything else that goes out is the result of an agent intent that the IntentFrame pipeline already saw, audited, and Guardian approved — for example an `HTTP_GET` action to a URL the agent named, a `SEND_EMAIL` to a recipient the agent named. There is no telemetry, no analytics, no phone-home.

---

## What lives on disk

All IntentFrame state lives under `~/.intentframe/` and `~/.intentframe-venvs/`. Nothing is written outside these roots.

```
~/.intentframe/
├── run/                              ← Unix sockets + PID files
│   ├── gateway.sock
│   ├── credential-vault.sock
│   ├── policy-registry.sock
│   ├── resource-registry.sock
│   ├── executor.sock
│   ├── intentframe.sock
│   ├── platform-server.sock          (macOS only)
│   ├── edi.sock                      (if EDI configured)
│   ├── jarvis.sock                   (if Jarvis enabled)
│   └── supervisor.pid
│
├── logs/                             ← per-service stdout/stderr
│   ├── policy-registry.log
│   ├── resource-registry.log
│   ├── executor.log
│   ├── intentframe-server.log
│   ├── supervisor.log
│   └── ... (per-process logs)
│
├── state/                            ← runtime state
│   └── root-demo.json                ← root-demo escalation flag (if armed)
│
├── policy/                           ← user policies (SQLite)
│
├── resource/                         ← VFS mounts + adapter registry (SQLite)
│
├── audit/                            ← executor audit trail (SQLite, hash-chained)
│
├── jarvis/                           ← Jarvis state (if enabled)
│   ├── memory.db
│   ├── sessions/
│   └── conversation history
│
└── email/                            ← EDI workspace (if EDI configured)
    ├── config.yaml                   ← email addresses (no passwords)
    ├── emails.db                     ← SQLite (WAL, FTS5) — full email mirror
    ├── attachments/                  ← downloaded attachments
    └── daemon.pid

~/.intentframe-venvs/
└── executor/                         ← executor's separate Python venv

macOS-managed (not under ~/.intentframe/):
└── ~/Library/Keychains/login.keychain-db
        ↑ where intentframe_credentials stores OpenAI API key,
          IMAP passwords, Telegram tokens, etc.
```

### What's in each location

| Location | Contents | Format | Owner process | Sensitive? |
|---|---|---|---|---|
| `~/.intentframe/run/*.sock` | Inter-process sockets | Unix domain socket | one per service | No (no data, just IPC endpoints) |
| `~/.intentframe/logs/*.log` | Service stdout/stderr | Plain text | written by each service, rotated by user | **Yes — may contain intent details, hash digests; credentials scrubbed by `redact_credentials`** |
| `~/.intentframe/state/` | Runtime flags (e.g. root-demo escalation marker) | JSON | gateway / supervisor | Low |
| `~/.intentframe/policy/` | User policies, intent limits, allowed actions | SQLite | policy-registry | **Yes — your security rules** |
| `~/.intentframe/resource/` | VFS mounts, adapter inventory | SQLite | resource-registry | Low |
| `~/.intentframe/audit/` | Hash-chained audit log of every executed action | SQLite | executor | **Yes — every action you took, with intent + result + timestamp** |
| `~/.intentframe/jarvis/memory.db` | Jarvis long-term memory | SQLite + OpenAI embeddings | jarvis | **Yes — conversation summaries and embeddings** |
| `~/.intentframe/jarvis/sessions/` | Conversation transcripts | JSON | jarvis | **Yes — what you said to Jarvis** |
| `~/.intentframe/email/emails.db` | Local mirror of every email in your synced folders | SQLite (WAL + FTS5) | EDI daemon | **Yes — your full email history (headers + bodies + attachments metadata)** |
| `~/.intentframe/email/attachments/` | Downloaded attachment payloads | Binary blobs | EDI daemon | **Yes — actual attachment files** |
| `~/.intentframe/email/config.yaml` | List of email addresses to sync | YAML | user-edited / EDI | Low (no passwords here) |
| `~/.intentframe-venvs/executor/` | Executor's isolated Python virtualenv | venv | setup script | No |
| macOS Keychain | Every credential (OpenAI key, IMAP passwords, Telegram token, OAuth secrets) | macOS-encrypted keychain | `credential-vault` reads it; written by setup or by user | **Yes — primary secret store** |

### Important properties of the on-disk model

- **Single root.** Everything IntentFrame writes lives under `~/.intentframe/` (plus the executor venv at `~/.intentframe-venvs/executor/` and credentials in the macOS Keychain). Backing up this directory backs up your IntentFrame state. Deleting it resets the system.
- **No plaintext credentials anywhere on disk.** `~/.intentframe/email/config.yaml` stores email addresses but never passwords. The credential vault reads from the macOS Keychain. `pydantic.SecretStr` ensures secrets show as `**********` in logs and tracebacks.
- **Audit trail is tamper-evident.** Every audit row links to the previous row's SHA-256 hash. Modifying any historical entry invalidates every later entry. See `executor_sdk/services/hash_chain.py` and [threat-model.md § Shipped Hardening](threat-model.md#shipped-hardening-beyond-the-core-pipeline).
- **Logs may contain intent text.** Logs include action types, target descriptions, reason strings, and decision paths. They do not include credentials (scrubbed by `intentframe_credentials.redaction.redact_credentials`). They may include filesystem paths and email subject lines that flowed through the pipeline.
- **No data is encrypted at rest by IntentFrame.** SQLite databases are plaintext (relying on filesystem permissions). If you need at-rest encryption, use FileVault (macOS) or LUKS (Linux). This is a documented gap, not a hidden choice.

---

## What leaves the machine

This is the critical privacy question, and the answer has three layers: IntentFrame-internal traffic, EDI traffic, and agent-driven traffic.

### Layer 1: IntentFrame-internal outbound — OpenAI only

The only outbound traffic that IntentFrame itself initiates without an agent intent is OpenAI API calls.

| Origin process | Calls OpenAI for | Endpoint |
|---|---|---|
| `intentframe-server` | Analysis Engine — semantic understanding of intents | `api.openai.com` |
| `intentframe-server` | AI Guardian — final ALLOW/BLOCK judgment | `api.openai.com` |
| `intentframe-server` | Onboarding engine — initial policy seeding | `api.openai.com` |
| `jarvis` | Agent reasoning loop | `api.openai.com` |
| `jarvis` | Conversation embeddings (sessions) | `api.openai.com` |
| `jarvis` | Memory embeddings + semantic search | `api.openai.com` |

What goes in the OpenAI calls:

- **From `intentframe-server`** — the structured intent fields (action, target, data, reason), policy context, and analysis prompts. Your filesystem paths, email recipients, command strings, etc. that the agent is *trying to act on* are visible to OpenAI for the duration of the request. The Analysis Engine and Guardian do not get raw user data they didn't already need to evaluate.
- **From `jarvis`** — the conversation context, retrieved memory snippets, and tool call results. Whatever you said to Jarvis, plus what it has remembered, can flow into the model.

What does **not** go to OpenAI:

- Your credentials (held in `executor` and in the vault, not in the LLM-calling processes)
- Audit log contents
- Email bodies (unless you ask Jarvis to read or summarize one — then that specific body is in the prompt)
- File contents (unless you ask the agent to read or process a specific file)

OpenAI's data handling is governed by your OpenAI API agreement. IntentFrame does not opt you in or out of training-data use; that's set on your OpenAI account.

#### The deterministic layers don't call OpenAI

The pipeline's deterministic gates (Command Shield, DeterministicGuardian, capability tagging, sandbox) do not call any LLM. Most safe actions and most catastrophic actions are decided without ever sending data to OpenAI. See [executor/security-model.md § How much gets decided before the executor](executor/security-model.md#how-much-gets-decided-before-the-executor).

In the root-demo evidence, ~80%+ of intents are decided before any LLM call. For typical Jarvis usage, deterministic ALLOW (the read-only fast-path) and the AI path are roughly mixed depending on what the agent does.

### Layer 2: EDI outbound — your email provider

If you've configured the email sync daemon (EDI), it talks **directly to your configured email provider** over IMAP and SMTP.

| Direction | Protocol | Destination | What flows |
|---|---|---|---|
| Inbound | IMAP IDLE (long-lived) | Your provider's IMAP server (e.g. `imap.gmail.com`) | New email notifications + headers |
| Inbound | IMAP fetch | Same | Headers, bodies, and attachments for sync |
| Outbound | SMTP | Your provider's SMTP server (e.g. `smtp.gmail.com`) | Sent messages from `EmailClient.send/reply/forward` |

Properties:

- **EDI is the only IntentFrame process that holds an IMAP/SMTP credential.** Both the executor's mail adapter and Jarvis's email tools call EDI's local `EmailClient` library — they never open IMAP connections themselves.
- **Connections are pooled and capped** at 3 concurrent per account, with a 25-minute IDLE cycle to stay below provider timeouts. See `external_data_ingestion/README.md`.
- **Local mirror lives on your machine.** EDI's whole point is to replace slow remote IMAP search with sub-millisecond local SQLite + FTS5 queries. Email content stays local once synced.
- **No third-party servers in the loop.** EDI talks to *your* provider directly. There is no IntentFrame email proxy or relay.

If you don't configure EDI, no email-related outbound traffic happens.

### Layer 3: Agent-driven outbound — actions you (or your agent) requested

The executor's adapters can make outbound network calls *as part of executing an approved intent*. These are not background traffic — every one corresponds to a specific `IntentFrame` that passed through the pipeline.

| Adapter | Outbound destination |
|---|---|
| `HttpApiAdapter` (`HTTP_GET`, `HTTP_POST`) | The URL the agent named in the intent |
| `MailAdapter` (`SEND_EMAIL`) | Your email provider's SMTP, via EDI |
| `BrowserAdapter` | Whatever URL the browser opens to |
| `TerminalAdapter` (`RUN_COMMAND`) | Wherever the command says (e.g. `curl https://api.example.com`), restricted by the kernel sandbox |
| `jarvis-telegram` (if enabled) | `api.telegram.org` (Telegram Bot API) |
| (future) Slack adapter | Slack API |
| (future) Calendar invite adapter | Provider's API |

Properties:

- Every one of these calls is preceded by an `IntentFrame` that the Guardian saw and approved. The audit log has a row for it.
- The kernel sandbox (Seatbelt SBPL) restricts what `RUN_COMMAND` subprocesses can reach over the network — by default, no network unless the deployment's `allowed_templates` includes a network template. See [executor.md § The kernel sandbox](executor.md#8-run_command-and-the-kernel-sandbox).
- The HTTP adapter is *not* sandboxed at the kernel level (it runs in the executor process), but its target URL is in the intent and visible to the Analysis Engine, which flags exfiltration patterns.

### What never happens

- **No telemetry.** IntentFrame does not phone home. There is no analytics endpoint, no crash reporter, no usage tracker.
- **No update server.** IntentFrame does not check for its own updates over the network.
- **No third-party logging.** Logs stay local.
- **No license verification.** No DRM, no activation server.
- **No remote policy fetch by default.** Policies live in the local `policy-registry`. (Future enterprise deployments may add policy mirrors; that would be opt-in.)

---

## Where each kind of secret lives

| Secret | Storage | Held in memory by |
|---|---|---|
| OpenAI API key | macOS Keychain (via `intentframe_credentials`) | `credential-vault`, `intentframe-server`, `jarvis` |
| IMAP / SMTP password (per email account) | macOS Keychain | `credential-vault`, `email-sync-daemon` |
| Telegram bot token | macOS Keychain | `credential-vault`, `jarvis-telegram` |
| OAuth tokens for adapter integrations | macOS Keychain | `credential-vault`, `executor` (when used by an adapter) |
| Audit log signing keys | (SQLite hash chain — no separate signing key) | — |
| Session / conversation data | `~/.intentframe/jarvis/` | `jarvis` only |

Boundary properties:

- **Credentials never appear in `IntentFrame` payloads.** Agents don't know them. The Actor SDK doesn't carry them. They're loaded inside the executor's adapter at call time.
- **Credentials are scrubbed from logs.** `intentframe_credentials.redaction.redact_credentials` is wired into structlog for every IntentFrame service.
- **Credentials are scrubbed from tracebacks.** `pydantic.SecretStr` ensures `repr()` shows `**********`.
- **Credentials don't cross process boundaries except via the vault.** The vault sets credentials into a child's environment at startup (so children don't have to keep calling back), but the source is always the vault, and only credentials that child *needs* are passed.

---

## Quick answers

| Question | Answer |
|---|---|
| Does IntentFrame send anything to the IntentFrame project's servers? | No. There is no IntentFrame-operated server. |
| Does IntentFrame send anything to OpenAI? | Yes — only the AE/Guardian validation calls (in `intentframe-server`) and the agent's own LLM calls (in `jarvis`). |
| Does IntentFrame send my email content to OpenAI? | Only if the agent reads or summarizes a specific email and that email's body ends up in the LLM prompt. Background email sync is local-only. |
| Does IntentFrame send my files to OpenAI? | Only if the agent reads or processes a specific file and that content ends up in the LLM prompt. |
| Does the executor connect to OpenAI? | No. The executor never makes LLM calls. It receives validated intents from `intentframe-server` and executes them. |
| Where is my audit log? | `~/.intentframe/audit/` — SQLite, hash-chained. |
| Where is my email stored? | `~/.intentframe/email/emails.db` if EDI is enabled; otherwise nowhere (IntentFrame doesn't touch email). |
| Where are my passwords stored? | macOS Keychain, accessed only via the credential-vault process. |
| Can I run IntentFrame fully offline? | The deterministic pipeline (Command Shield, DG, sandbox) works offline. The AI gates (AE, AI Guardian) require OpenAI; they fail-closed to BLOCK on unavailability. |
| Can I disable EDI? | Yes — don't configure email accounts, and the daemon doesn't start. |
| Can I disable Jarvis? | Yes — Jarvis is optional; the gateway only starts it if enabled. The IntentFrame pipeline runs without it. |
| Can I delete everything? | `rm -rf ~/.intentframe ~/.intentframe-venvs` and clear IntentFrame entries from the macOS Keychain. |
| Is my data encrypted at rest? | Not by IntentFrame. Use FileVault / LUKS for at-rest encryption. |
| Does anything talk on a TCP port? | No. All IntentFrame IPC uses Unix domain sockets in `~/.intentframe/run/`. |

---

## Documented gaps

These are honest limitations, not hidden behaviors:

- **No at-rest encryption** — SQLite files in `~/.intentframe/` are plaintext. Filesystem permissions are the only barrier. Use full-disk encryption.
- **Logs may contain intent text** — action types, targets, reasons, paths, and decision paths appear in plaintext logs. Credentials are scrubbed; intent metadata is not.
- **No log rotation** — logs in `~/.intentframe/logs/` grow without bound until you rotate them externally. (Tracked.)
- **OpenAI is the AI provider** — the AE and Guardian are tied to OpenAI in the current implementation. Provider abstraction is on the roadmap (Anthropic, local models). Until then, your AE/Guardian prompts are subject to OpenAI's data policies.
- **Off-host audit retention is not shipped** — audit logs are local SHA-256 hash-chained but not signed for off-host integrity. See [faq.md § Q11](faq.md#q11-what-does-intentframe-not-claim).
- **Jarvis memory embeddings live with OpenAI metadata** — embeddings are stored locally, but the model that produced them is OpenAI's. You can clear `~/.intentframe/jarvis/memory.db` to reset.

---

## Related documents

- [README.md](README.md) — Top-level docs index
- [processes.md](processes.md) — Which process holds what, which process talks to what; and "Why Unix domain sockets"
- [credentials-vault.md](credentials-vault.md) — Public reference for the vault: where each kind of secret lives, how it's delivered, what's protected
- [email-sync.md](email-sync.md) — EDI public reference: storage layout, IMAP/SMTP traffic profile
- [registries.md](registries.md) — Where policy / resource configuration lives on disk
- [executor.md](executor.md) — The executor's credential isolation and audit model
- [executor/why-foundation.md](executor/why-foundation.md) — Why process isolation underwrites the privacy story
- [threat-model.md](threat-model.md) — In-scope vs out-of-scope threats
- [faq.md](faq.md) — Common objections answered
- [`../external_data_ingestion/README.md`](../external_data_ingestion/README.md) — EDI's full design
- [`../packages/intentframe-credentials/README.md`](../packages/intentframe-credentials/README.md) — Credential vault details
