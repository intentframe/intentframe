# Runtime Processes

> What actually runs on your machine when you start IntentFrame, what each process does, and how they talk to each other.

When you run `uv run intentframe-gateway-cli`, you're not starting one program — you're starting an orchestrator that spawns up to ten long-lived processes, each with a narrow job. This document is the canonical map.

The architecture is process-isolated by design: credentials live in one process, the executor runs in another, the AI judgment layers run in a third, and so on. Process boundaries are part of the security story (see [executor/why-foundation.md](executor/why-foundation.md)) and part of the privacy story (see [privacy.md](privacy.md)).

---

## The full process tree

```
intentframe-gateway-cli                ← 1 entry-point process you launch
  │
  │  Spawned by ProcessManager (intentframe_gateway/process_manager.py)
  │  in this order:
  │
  ├── credential-vault                 ← always (Step 1)
  │
  ├── email-sync-daemon (EDI)          ← if EDI configured (Step 3, optional)
  │
  ├── platform-server (Swift)          ← macOS only (Step 5)
  │
  ├── supervisor                       ← always (Step 6 — manages 4 children)
  │     │
  │     │  Spawned by supervisor in dependency order
  │     │  (supervisor/config.py, supervisor/main.py):
  │     │
  │     ├── policy-registry            (uvicorn, UDS)
  │     ├── resource-registry          (uvicorn, UDS)
  │     ├── executor                   (uvicorn, UDS — separate venv)
  │     └── intentframe-core           (uvicorn, UDS)
  │           depends_on: [policy-registry,
  │                        resource-registry,
  │                        executor]
  │
  ├── jarvis                           ← if Jarvis enabled (Step 8)
  │
  └── jarvis-telegram                  ← if Telegram credentials present (Step 9)
```

Source of truth: `intentframe_gateway/server.py` (lifespan, steps 1–9) and `supervisor/main.py` + `supervisor/config.py` (the four supervised services).

All inter-process communication uses **Unix domain sockets** under `~/.intentframe/run/`. Nothing listens on a TCP port by default. There is no network IPC between IntentFrame components.

---

## Process-by-process reference

### 1. `intentframe-gateway-cli` — the entry point

| | |
|---|---|
| **What it is** | The single program you launch. A FastAPI app served on a Unix socket (`~/.intentframe/run/gateway.sock`). |
| **Source** | `intentframe_gateway/server.py` |
| **Job** | Starts the credential vault, gates on mandatory credentials (OpenAI key), starts EDI / platform-server / supervisor / Jarvis / Telegram in order, exposes a unified API for frontends. |
| **OpenAI calls** | No |
| **Outbound network** | No |
| **Holds credentials?** | No — passes runtime env to children, never inspects secrets |
| **Lifecycle** | You start it; it stops everything else when it exits |

The gateway is a thin orchestrator. It owns the *startup choreography* but does no policy decisions, no AI calls, and no actions itself.

### 2. `credential-vault` — the secret store

| | |
|---|---|
| **What it is** | A Unix-socket server that backs the `intentframe_credentials` library. |
| **Source** | `intentframe_credentials/intentframe_credentials/server.py` |
| **Job** | Returns secrets (OpenAI API key, IMAP passwords, Telegram tokens) on request. Backed by macOS Keychain (or env-overlay for dev). |
| **Storage** | macOS Keychain via `keyring_backend.py`; no plaintext on disk |
| **OpenAI calls** | No |
| **Outbound network** | No |
| **Lifecycle** | First service started; last service stopped |

Other processes that need a secret call into the vault over the socket. Secrets travel into the requesting process's memory once, and adapters that need them (e.g. the OpenAI client in `intentframe-core`, IMAP connections in EDI) hold them as `pydantic.SecretStr` so tracebacks and logs show `**********` instead of plaintext.

### 3. `email-sync-daemon` (EDI) — IMAP/SMTP service

| | |
|---|---|
| **What it is** | A standalone IMAP IDLE + SMTP daemon. The "dedicated email service" in IntentFrame. |
| **Source** | `external_data_ingestion/external_data_ingestion/email/daemon.py` |
| **Job** | Maintains a local SQLite mirror of your email (IMAP IDLE for real-time INBOX updates, periodic sync for other folders, SMTP for sending). Provides an `EmailClient` library that other processes use to read/write mail without each one talking IMAP directly. |
| **Storage** | `~/.intentframe/email/emails.db` (SQLite, WAL mode, FTS5), `~/.intentframe/email/attachments/`, `~/.intentframe/email/config.yaml` |
| **OpenAI calls** | No |
| **Outbound network** | **Yes — IMAP and SMTP to your configured email provider** (Gmail, Outlook, iCloud, Yahoo, custom). Connections are pooled, capped at 3 concurrent per account, and re-cycled every ~25 minutes. |
| **Holds credentials?** | Yes — IMAP password fetched from vault at startup, held as `SecretStr` in memory only |
| **Lifecycle** | Optional. Started by the gateway after credential-vault if EDI is configured. |

EDI is the single point of contact with email providers. Both the executor's mail adapter and Jarvis's email tools go through EDI's client library — they never open their own IMAP connections. This is what keeps connection counts low (Gmail caps simultaneous IMAP connections per account at 15) and what gives the agent fast local search via the SQLite FTS5 mirror instead of slow remote IMAP `SEARCH` calls.

See `external_data_ingestion/README.md` for the full design.

### 4. `platform-server` (Swift) — macOS native bridge

| | |
|---|---|
| **What it is** | A Swift binary that exposes Apple's EventKit / Contacts / Messages APIs over a Unix socket. |
| **Source** | `macos-appkit-server/` |
| **Job** | Calendar, Reminders, Contacts, Notes, iMessage reads. macOS-only. |
| **Storage** | None of its own — bridges to Apple's databases (`~/Library/...`) under TCC permission |
| **OpenAI calls** | No |
| **Outbound network** | No (Apple-managed iMessage sync happens at OS level, not via this process) |
| **Holds credentials?** | No (TCC handles permissions) |
| **Lifecycle** | macOS only. Started by the gateway before the supervisor so the executor can reach it during its startup checks. |

Code-signed with a stable identity (`IntentFrame Dev`) so macOS TCC permissions persist across rebuilds. On non-macOS deployments this process is absent and the corresponding adapters report "unavailable".

### 5. `supervisor` — process manager

| | |
|---|---|
| **What it is** | A Python supervisor that spawns the four IntentFrame core services and monitors their health. |
| **Source** | `supervisor/main.py`, `supervisor/config.py`, `supervisor/health.py` |
| **Job** | Topological-order startup, per-service health checks, automatic restart on crash (up to `max_restarts`), graceful shutdown |
| **OpenAI calls** | No |
| **Outbound network** | No |
| **Lifecycle** | Started by the gateway in Step 6; supervises 4 children until shutdown |

Like systemd, but only for IntentFrame's four uvicorn services. Writes its PID to `~/.intentframe/run/supervisor.pid`, sets up a fresh process group so the gateway can kill the entire tree with one `killpg()`.

### 6. `policy-registry` — user policy store

| | |
|---|---|
| **What it is** | uvicorn FastAPI app on `~/.intentframe/run/policy-registry.sock` |
| **Source** | `policy_registry/server.py` |
| **Job** | Stores user policies, intent limits, allowed actions, allowed/denied capability sets. Read by the Guardian at every validation call. |
| **Storage** | Local SQLite at `~/.intentframe/policy/` |
| **OpenAI calls** | No |
| **Outbound network** | No |
| **Restart-on-crash** | Yes |

The policies are the *authority* the Guardian enforces against. They're declared at registration time, not inferred at runtime — this is the property that prevents a compromised agent from talking the Guardian into a policy exception.

### 7. `resource-registry` — VFS and adapter registry

| | |
|---|---|
| **What it is** | uvicorn FastAPI app on `~/.intentframe/run/resource-registry.sock` |
| **Source** | `resource_registry/server.py` |
| **Job** | Tracks VFS mounts (which real paths map to which virtual paths) and the registered adapter inventory. |
| **Storage** | Local SQLite at `~/.intentframe/resource/` |
| **OpenAI calls** | No |
| **Outbound network** | No |
| **Restart-on-crash** | Yes |

Together with policy-registry, this is the "configuration plane" — what the user has authorized, what resources exist, what adapters are wired up. The pipeline reads from both at every intent.

### 8. `executor` — the only process with credentials and IO

| | |
|---|---|
| **What it is** | uvicorn FastAPI app on `~/.intentframe/run/executor.sock`. Runs in its own Python virtualenv (`~/.intentframe-venvs/executor/`) so its dependencies are isolated from the rest of the system. |
| **Source** | `executor/server.py`, `executor/gateway.py`, `intentframe_executor_pack_macos/adapters/*.py` |
| **Job** | Executes validated intents through 18 typed adapters (Files, Mail, Calendar, Browser, Terminal, …). Holds all credentials. Wraps every `RUN_COMMAND` subprocess in a Seatbelt sandbox. Writes the hash-chained audit log. |
| **Storage** | SQLite audit DB; in-memory credential cache (loaded from vault) |
| **OpenAI calls** | No |
| **Outbound network** | **Yes — but only via approved adapters acting on agent intents.** HTTP adapter calls the URLs the agent named; mail adapter goes through EDI; etc. None of this is background traffic. |
| **Holds credentials?** | **Yes — every credential** (OpenAI key for downstream services it spawns, OAuth tokens, API keys). Only process that does. |
| **Restart-on-crash** | Yes |

This is the process the entire IntentFrame security model rests on. See [executor.md](executor.md) for the full conceptual treatment and [executor/architecture.md](executor/architecture.md) for the internal four-layer design.

### 9. `intentframe-core` — pipeline, AE, and Guardian

| | |
|---|---|
| **What it is** | uvicorn FastAPI app on `~/.intentframe/run/intentframe.sock` |
| **Source** | `intentframe_server/server.py`, `intentframe_server/pipeline.py`, `intentframe_components/{analysis,guardian,prompt}/...` |
| **Job** | The validation pipeline. Receives `IntentFrame` requests from agents (via the Actor SDK), runs Command Shield → Deterministic Guardian → Analysis Engine → AI Guardian, and on ALLOW forwards the validated intent to the executor over its UDS. |
| **Storage** | None directly (reads policies via policy-registry socket) |
| **OpenAI calls** | **Yes** — the Analysis Engine (`intentframe_components/analysis/engine.py`) and AI Guardian (`intentframe_components/guardian/engine.py`) both call OpenAI. AE uses `gpt-4o-mini` at temperature 0; Guardian uses a reasoning model. |
| **Outbound network** | **Only OpenAI API**, only on the UNDECIDED path (deterministic gates handle most traffic without an LLM) |
| **Holds credentials?** | OpenAI API key only (received via env at startup from the gateway, which fetched it from the vault) |
| **Restart-on-crash** | Yes |
| **Depends on** | policy-registry, resource-registry, executor |

This is where Guardian and the Analysis Engine actually *run*. When you read "the Guardian decides," the decision is happening in this process. It's also the only IntentFrame-internal process that talks to OpenAI.

### 10. `jarvis` — the agent application (optional)

| | |
|---|---|
| **What it is** | The reference local-assistant agent built on top of IntentFrame. |
| **Source** | `jarvis_pa/jarvis/` |
| **Job** | Conversational agent loop, memory, tools. Runs its own LLM. Submits every action as an `IntentFrame` to `intentframe-core` via the Actor SDK. |
| **Storage** | `~/.intentframe/jarvis/` (memory, conversation history) |
| **OpenAI calls** | **Yes** — agent reasoning loop (`jarvis/agent.py`), session embeddings (`jarvis/session.py`), memory embeddings and search (`jarvis/memory.py`, `jarvis/memory_search.py`, `jarvis/memory_index.py`) |
| **Outbound network** | **Only OpenAI API** for its own reasoning. Every other action it wants to take goes through the IntentFrame pipeline. |
| **Holds credentials?** | OpenAI key only (passed via env from the gateway) |
| **Lifecycle** | Optional. Started by the gateway in Step 8 if Jarvis is enabled. |

The important property: Jarvis can think freely (OpenAI calls happen in-process), but it cannot act freely. Every side effect — reading a file, sending an email, running a command — goes out through `actor.submit()` to `intentframe-core` for validation, and only then to the executor. Jarvis does not hold IMAP, calendar, or filesystem credentials. Those live in the executor.

### 11. `jarvis-telegram` — Telegram bridge (optional)

| | |
|---|---|
| **What it is** | A bridge that exposes Jarvis to a Telegram bot. |
| **Source** | `jarvis_telegram/` |
| **Job** | Relays Telegram messages to Jarvis and vice versa |
| **OpenAI calls** | No (it forwards to Jarvis, which makes the calls) |
| **Outbound network** | **Yes — Telegram Bot API** (`api.telegram.org`) |
| **Holds credentials?** | Telegram bot token only (from vault) |
| **Lifecycle** | Optional. Started by the gateway in Step 9 if Telegram credentials exist. |

---

## Pipeline ↔ process mapping

The IntentFrame *pipeline* (Agent → Actor → AE → Guardian → Executor) is a logical flow. The mapping to real processes is not 1:1:

| Pipeline component | Lives in process |
|---|---|
| Third-party agent / Jarvis | `jarvis` (or any other agent process) |
| Actor SDK | The agent's process — Actor is a library, not a service |
| Command Shield | `intentframe-core` (deterministic, no LLM) |
| Deterministic Guardian | `intentframe-core` |
| Analysis Engine | `intentframe-core` (LLM call to OpenAI) |
| AI Guardian | `intentframe-core` (LLM call to OpenAI) |
| Executor gateway, adapters, sandbox, audit, vault | `executor` |
| Policy storage | `policy-registry` |
| VFS / adapter registry | `resource-registry` |
| Email IMAP/SMTP | `email-sync-daemon` (executor's mail adapter and Jarvis tools both call this) |
| Calendar / Contacts / iMessage / Reminders | `platform-server` (executor adapters call this) |

The two processes that hold the most weight: **`executor`** (the only one with credentials, the only one that touches resources) and **`intentframe-core`** (where the validation pipeline runs).

---

## Inter-process communication

All IPC uses Unix domain sockets in `~/.intentframe/run/`. Each socket is owned by one process and consumed by others over HTTP (uvicorn + FastAPI on UDS).

```
~/.intentframe/run/
├── gateway.sock              ← intentframe-gateway-cli
├── credential-vault.sock     ← credential-vault
├── policy-registry.sock      ← policy-registry
├── resource-registry.sock    ← resource-registry
├── executor.sock             ← executor
├── intentframe.sock          ← intentframe-core
├── platform-server.sock      ← platform-server (macOS only)
├── edi.sock                  ← email-sync-daemon (if running)
├── jarvis.sock               ← jarvis (if running)
└── supervisor.pid            ← PID file (not a socket)
```

### Why Unix domain sockets

Unix domain sockets are the only IPC primitive used between IntentFrame components — between the gateway and supervisor, between the supervisor and the four core services, between the executor and the platform server, between EDI's daemon and its clients, between any frontend and the gateway. There is intentionally no TCP, no message queue, no IPC bus. The choice is deliberate, and worth being explicit about because it underwrites several security and operational properties.

**1. No network exposure — even loopback.**
A TCP listener on `127.0.0.1` is still a TCP listener. It's reachable from any process on the machine, accessible from container sidecars, traversable over `ssh -L` port-forwarding, and (with misconfiguration) bindable on `0.0.0.0`. Unix sockets have *no network presence at all* — they live in the filesystem namespace. There is no port number, no bind address, no remote-host concept. If you don't have access to the file, you cannot reach the service. This eliminates an entire class of "I accidentally exposed it" mistakes.

**2. The filesystem is the access-control list.**
A Unix socket's permission bits, ownership, and parent-directory permissions are the access-control mechanism. `~/.intentframe/run/` is created with the user's permissions; only that user's processes can connect. There's no extra auth layer to mis-configure. Compare to TCP, where you'd need a token, a TLS cert, or both — and either of those fails open if you forget to wire it up. Filesystem permissions fail closed: if the bits are wrong, the socket simply isn't reachable.

**3. Local-only is part of the security model.**
IntentFrame's threat model assumes the user's machine is the trust boundary. Credentials live on the device, in the OS keyring. The pipeline runs on the device. The only outbound traffic is what's documented in [privacy.md](privacy.md) (OpenAI, IMAP/SMTP, agent-driven adapters). Putting any of the inter-component IPC on the network would punch a hole in this boundary — even if it's "just localhost." Unix sockets make local-only the *only possible* mode of operation for component-to-component traffic, structurally.

**4. SO_PEERCRED — credentials of the connecting process are knowable.**
Unix sockets expose the connecting process's UID, GID, and PID to the listener via `SO_PEERCRED` (Linux) / `LOCAL_PEERCRED` (macOS). TCP does not. The vault doesn't currently use this for per-caller ACLs (noted as a gap in [credentials-vault.md § Documented gaps](credentials-vault.md#documented-gaps)), but the building block is there: a future enhancement can ACL the vault socket on caller UID without inventing a token system.

**5. Lower overhead, simpler code paths.**
Unix sockets bypass the TCP stack — no checksums, no fragmentation, no congestion control, no port allocation. Connection setup is a syscall, not a three-way handshake. For a system that does a lot of small IPC calls (every intent goes through 4–5 services, each over UDS), the latency difference is real and the code paths are simpler to reason about.

**6. No port-allocation problems.**
TCP would require either fixed port numbers (which conflict with anything else on the machine) or dynamic port selection (which means each frontend has to discover what port each service ended up on). Unix sockets have stable, well-known paths under `~/.intentframe/run/`. No port-conflict story to maintain.

**7. Multiple instances coexist by directory, not by port.**
Different IntentFrame instances on the same machine can be isolated by giving each its own `INTENTFRAME_RUN_DIR`. If two instances try to share one directory, they compete for the same socket files; the supervisor and gateway both kill stale predecessors via PID files before binding (`supervisor/main.py::_kill_stale_supervisor`).

**Tradeoffs we're accepting**

- **Local-machine only.** A Unix socket cannot be consumed from another host. This is by design today (the cloud product is a separate roadmap item that would change the transport to gRPC — see [Deployment variations](#deployment-variations)). For local-first agents, this is the correct constraint.
- **Container/VM bridging requires bind mounts.** If you run IntentFrame inside a container and want a host-side frontend to reach it, you bind-mount the run directory. This is well-understood operationally and is preferable to opening a TCP port.
- **Windows compatibility.** Modern Windows (10+) supports Unix sockets, but some legacy tooling doesn't. IntentFrame is currently macOS / Linux first; full Windows support would re-validate every socket path.

**What this rules out, by construction**

- A remote attacker who hasn't compromised your user account cannot reach the vault, the executor, the policy registry, or any other IntentFrame service — there is no port to scan.
- A container running as a different user on the same host cannot reach IntentFrame's services — the socket directory permissions exclude them.
- A misconfiguration cannot accidentally expose IntentFrame to the network — there's no `bind_address` to set wrong.

For the implementation patterns, every IntentFrame service uses uvicorn's `--uds` flag, FastAPI for the HTTP API, and a simple Unix-socket-aware HTTP client (`httpx.AsyncClient` with `transport=httpx.AsyncHTTPTransport(uds=...)`). The wire format is HTTP/JSON; Unix sockets are just the transport.

---

## Process lifecycle

```
START
  └─ gateway.lifespan() runs:
       Step 1:  start credential-vault          [always]
       Step 2:  check OpenAI key in vault       [gates further startup]
       Step 3:  start EDI                       [if configured]
       Step 4:  build env (config + secrets) for children
       Step 5:  start platform-server           [macOS only]
       Step 6:  spawn supervisor subprocess
                  ├─ supervisor starts policy-registry
                  ├─ supervisor starts resource-registry
                  ├─ supervisor starts executor
                  └─ supervisor starts intentframe-core   [depends on above]
       Step 7:  bootstrap (seed policies, register workspace)
       Step 8:  start jarvis                    [if Jarvis enabled]
       Step 9:  start jarvis-telegram           [if Telegram credentials present]
       Step 10: open AppStore + UnifiedEventStream
       READY

STOP (Ctrl+C or shutdown)
  └─ gateway.lifespan() teardown runs in reverse:
       stop jarvis, telegram
       stop supervisor (which stops its 4 children in reverse order)
       shutdown platform-server (HTTP /shutdown call for graceful TCC release)
       stop EDI (SIGTERM)
       stop credential-vault
       remove gateway.pid
```

Source: `intentframe_gateway/server.py` lifespan function.

---

## Privilege model

By default, **every IntentFrame process runs as the normal user**. None of them require root. The only place that can become privileged is one specific subprocess:

- The **executor's `RUN_COMMAND` child subprocess** can request `sudo -n sandbox-exec` for the root demo (`docs/root_demo/executor-root-mode.md`).
- This requires the machine to be armed with the root-demo installer (`intentframe_setup_root_demo.sh`).
- Even when escalated, the subprocess runs inside a kernel-enforced Seatbelt sandbox.
- The executor service itself, the gateway, the supervisor, the policy services, the agent — all run as the normal user.

See [faq.md § Q10](faq.md#q10-does-the-executor-run-as-root) and [root_demo/executor-root-mode.md](root_demo/executor-root-mode.md) for the full privilege model.

---

## What runs without OpenAI?

If the OpenAI API key is missing or invalid, the gateway enters **partial startup**: credential-vault starts, the gateway is up, but the supervisor's services are not started. This is gating, not a degraded mode.

If OpenAI is *unavailable mid-run* (network down, API outage), the deterministic layers (`command_shield`, `DeterministicGuardian`, capability gates, sandbox) still work; UNDECIDED intents would fail-closed to BLOCK because the Analysis Engine and AI Guardian cannot reach the model.

The deterministic-only test suites (`command_shield/tests/`, most of `tests/`) run without an OpenAI key.

---

## What changes per deployment

The process model above is the macOS / Jarvis deployment. Other deployments adjust the process set:

| Deployment | Different processes |
|---|---|
| **macOS Jarvis (default)** | All 11 processes shown above |
| **Demo / dev** | No platform-server (or stubbed), no Telegram bridge, no Jarvis (depends on what you start) |
| **Linux core** | No platform-server (Swift binary is macOS-only); native adapters become "unavailable"; everything else identical |
| **Cloud (planned)** | Transport changes from UDS to gRPC; platform-server replaced by cloud-equivalent adapters; credential vault may delegate to KMS / Vault |

The supervisor's four core services (`policy-registry`, `resource-registry`, `executor`, `intentframe-core`) are present in every deployment.

---

## Related documents

- [README.md](README.md) — Top-level docs index
- [modules.md](modules.md) — Workspace map: each module → its purpose, source, and process
- [privacy.md](privacy.md) — Where data lives on disk and what leaves the machine
- [credentials-vault.md](credentials-vault.md) — Public reference for the `credential-vault` process
- [registries.md](registries.md) — What the `policy-registry` and `resource-registry` processes serve
- [email-sync.md](email-sync.md) — Public reference for the `email-sync-daemon` (EDI)
- [macos-platform-server.md](macos-platform-server.md) — Public reference for the `macos-appkit-server` Swift bridge
- [executor.md](executor.md) — The Executor in depth
- [executor/architecture.md](executor/architecture.md) — Executor internals (note: that doc's "four layers" are *internal* to the executor process; not to be confused with the four supervised services here)
- [executor/why-foundation.md](executor/why-foundation.md) — Why process isolation matters for safety
- [architecture.md](architecture.md) — The pipeline architecture (logical, not process-level)
- [faq.md § Q10](faq.md#q10-does-the-executor-run-as-root) — Privilege model
- [`../external_data_ingestion/README.md`](../external_data_ingestion/README.md) — EDI design and configuration
