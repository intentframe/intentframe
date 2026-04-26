# IntentFrame Gateway

The top-level product orchestrator and "backend for any frontend" — a single FastAPI service on one Unix Domain Socket that starts the entire IntentFrame system, manages its lifecycle, and exposes the platform through one coherent API.

Any frontend (native app, interactive CLI, web, Telegram, or future network clients) talks to `gateway.sock` and nothing else.

## Why This Exists

The platform has multiple HTTP services on separate Unix sockets.  Without the gateway, every frontend must:

- Know the socket path for each service
- Coordinate multi-step flows across sockets
- Manage process lifecycle (start/stop all services)
- Implement its own health aggregation
- Have no access to app-level preferences or a unified event stream

The gateway eliminates all of that.

## Architecture

```
┌─────────────────────────────────────┐
│          Any Frontend               │
│  (Native / CLI / Web / Telegram)    │
└───────────────┬─────────────────────┘
                │
         gateway.sock
                │
┌───────────────▼─────────────────────┐
│       intentframe_gateway           │
│         (orchestrator)              │
│                                     │
│  Manages ──→ credential-vault       │
│  Manages ──→ supervisor             │
│     └──→ policy-registry            │
│     └──→ resource-registry          │
│     └──→ executor                   │
│     └──→ intentframe-core           │
│  Manages ──→ jarvis                 │
│  Manages ──→ edi (email daemon)     │
│  Manages ──→ telegram (bot)         │
│  Opens   ──→ platform-server (macOS)│
│                                     │
│  Proxy  to all sockets above        │
│  System (health, logs, lifecycle)   │
│  Config (SQLite preferences)        │
│  Events (merged event stream)       │
└─────────────────────────────────────┘
```

### Startup Sequence

The gateway is the **root process**.  It starts everything in dependency order:

| Step | What happens | Detail |
|------|-------------|--------|
| 1 | Start credential-vault | UDS server, must be healthy before anything else |
| 2 | Check mandatory credentials | OpenAI API key required; partial startup mode if missing |
| 3 | Start EDI (fire-and-forget) | Email sync daemon, only if email accounts configured |
| 4 | Build combined env | Merge non-sensitive config YAML + vault secrets; see [Env injection](#env-injection-three-layers-one-dict) |
| 5 | Detect root-demo escalation | Read `~/.intentframe/state/root-demo.json` + check `/etc/sudoers.d/intentframe-run`; inject `INTENTFRAME_ESCALATION_ARMED=0\|1` into supervisor env |
| 6 | Start supervisor | Spawns 4 infra services (policy-registry, resource-registry, executor, intentframe-core); inherits `INTENTFRAME_ESCALATION_ARMED` |
| 7 | Start platform server (macOS) | Via `open .app` for TCC permissions; non-fatal if unavailable |
| 8 | Bootstrap | Seed policies and workspace (idempotent) |
| 9 | Start Jarvis | AI agent, needs runtime env (OpenAI key) |
| 10 | Start Telegram | Only if bot token exists in vault and Jarvis is healthy |
| 11 | Open store and event stream | SQLite preferences + unified health/event polling |

### Env injection (three layers, one dict)

The gateway builds a **single flat `{ENV_NAME: value}` dict** that gets injected into every child process.  That dict is the merge of three layers:

```
hardcoded defaults          (source code — e.g. user_id = "jarvis_default")
  ↑ overridden by
~/.intentframe/gateway.yaml  (non-sensitive — user_id, Telegram allowed_user_id, custom vars)
  ↑ overridden by
credential vault runtime_env (secrets — API keys, tokens, passwords)
```

**Layer 1 — System config YAML** (`config_loader.build_config_env()`):
Reads `~/.intentframe/gateway.yaml` and maps structured keys and an explicit `env:` section into env vars:

```yaml
# ~/.intentframe/gateway.yaml
identity:
  user_id: jarvis_default          # → JARVIS_USER_ID

telegram:
  allowed_user_id: 123456789       # → JARVIS_TELEGRAM_ALLOWED_USER_ID

env:                                # explicit passthrough — literal env var names
  MY_CUSTOM_VAR: some_value
```

Well-known mappings (in `config_loader.WELL_KNOWN_CONFIG`):

| YAML key | Env variable |
|----------|-------------|
| `identity.user_id` | `JARVIS_USER_ID` |
| `telegram.allowed_user_id` | `JARVIS_TELEGRAM_ALLOWED_USER_ID` |

**Layer 2 — Vault secrets** (`CredentialGate.build_runtime_env()`):
Loads all credentials stored with `delivery_mode=runtime_env` (e.g. `OPENAI_API_KEY`, `JARVIS_TELEGRAM_BOT_TOKEN`).  Secrets always win on collision with config YAML.

**Merge in `server.py`**:

```python
config_env  = build_config_env()        # non-sensitive YAML
runtime_env = gate.build_runtime_env()   # vault secrets
combined_env = {**config_env, **runtime_env}
```

This combined dict is passed to every process that accepts an env overlay:

- The **supervisor** (and thus its four infra children)
- **Jarvis** (`start_jarvis(env=combined_env)`)
- **Telegram** (`start_telegram(env=combined_env)`)

Unused variables are simply ignored by each binary.

The system config YAML is also used by `bootstrap.py` to resolve `user_id` for policy and workspace seeding, instead of hardcoding it.

Manage the YAML via CLI (`env list`, `env set`, `env delete`) or API (`/system/config-env`).

### Shutdown

All shutdown goes through one API:

```
POST /system/shutdown  →  gateway SIGTERM  →  lifespan teardown
```

The lifespan teardown runs in order:
1. `POST /shutdown` on platform server (macOS only)
2. Stop managed processes (telegram, edi, jarvis, vault) via `SIGTERM`
3. Stop supervisor (which stops its 4 infra services)
4. Close proxies
5. Remove `gateway.pid`

Each managed process gets `SIGTERM` then a 10-second grace period before `SIGKILL`.  The EDI daemon handles `SIGTERM` cleanly — it force-closes IDLE IMAP sockets, drains connections, waits for in-flight fetches, and closes its SQLite DB (typically 2-5 seconds).

Both a native frontend and the CLI use this same flow.  A native frontend can fall back to `kill(-pgid, SIGKILL)` after a timeout.

### PID Tracking

| File | Written by | Purpose |
|------|-----------|---------|
| `~/.intentframe/run/gateway.pid` | Gateway lifespan | Root process; killing this cascades to all Python children |
| `~/.intentframe/run/supervisor.pid` | Supervisor | Stale process detection on restart |
| `~/.intentframe/run/platform-server.pid` | Swift entrypoint | Independent process; needs its own PID for orphan cleanup |

## Running

### Via the interactive CLI

```bash
uv run intentframe-gateway-cli
```

This starts the gateway as a subprocess (if not already running), waits for health, then drops into an interactive REPL where you can chat with Jarvis, view status, stream logs, manage services, and quit.

### Via a native frontend

A native frontend spawns the gateway via the `intentframe-gateway-backend` entry point.  Progress events stream via JSON on stdout.

### Standalone (development)

```bash
uvicorn intentframe_gateway.server:app --uds /tmp/gateway.sock --log-level info
```

### Entry points

| Command | Module | Description |
|---------|--------|-------------|
| `intentframe-gateway-cli` | `intentframe_cli.main:main` | Interactive CLI (starts gateway + REPL) |
| `intentframe-gateway-backend` | `intentframe_gateway.entry:backend_main` | Native frontend entry (spawns gateway with JSON progress) |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INTENTFRAME_RUN_DIR` | `~/.intentframe/run` | Directory containing `.sock` and `.pid` files |
| `INTENTFRAME_DATA_DIR` | `~/.intentframe/data` | Directory for `gateway.db` (SQLite) |
| `INTENTFRAME_LOG_DIR` | `~/.intentframe/logs` | Directory containing `{service}.log` files |
| `INTENTFRAME_FRONTEND_MODE` | unset | Set to `1` for JSON progress on stdout (native frontend) |
| `PLATFORM_SERVER_APP` | auto-detected | Path to `macos-appkit-server.app` bundle |
| `INTENTFRAME_PROFILE` | `user` | Set to `root` to activate the Jarvis root demo profile (controls bootstrap and `EXECUTOR_CONFIG` default). Normally set by the CLI via `--profile root`. |
| `EXECUTOR_CONFIG` | `jarvis_pa/executor.yaml` | Path to the executor YAML config file. Overridden to `jarvis_pa/executor_root.yaml` when `INTENTFRAME_PROFILE=root` and the operator has not set it explicitly. |
| `JARVIS_USER_ID` | (set by gateway) | Profile-scoped policy identity passed to Jarvis. The user profile uses the base id (for example `jarvis_default`); the root profile uses the suffixed id (for example `jarvis_default_root`) so Jarvis loads the same policy record that bootstrap seeded. |
| `INTENTFRAME_ESCALATION_ARMED` | (set by gateway) | Injected by the gateway into the supervisor/executor env at startup. `1` if root-demo is installed and armed (`/etc/sudoers.d/intentframe-run` + `~/.intentframe/state/root-demo.json` both present), `0` otherwise. The executor's `MacOSSandboxEngine` reads this to decide whether to prepend `sudo -n` to `sandbox-exec`. Never set this manually. |

## Module Structure

```
intentframe_gateway/
├── __init__.py
├── server.py              # FastAPI app, lifespan (orchestration sequence, PID file)
├── entry.py               # Process entry point: backend_main() (native frontend)
├── proxy.py               # UDSProxy class + proxy_websocket() helper
├── config.py              # GatewayConfig (Pydantic): socket paths, backends
├── config_loader.py       # System config YAML loader (~/.intentframe/gateway.yaml)
├── credential_gate.py     # Mandatory/optional credential checks + secret env builder
├── escalation.py          # Root-demo capability detection: reads root-demo.json marker
│                          #   + sudoers file; produces EscalationState used by server.py
│                          #   (to inject INTENTFRAME_ESCALATION_ARMED) and routes/system.py
│                          #   (to populate root_demo block in /system/health)
├── process_manager.py     # Manages vault, jarvis, edi, telegram, platform-server
├── bootstrap.py           # Idempotent policy/workspace seeding
├── store.py               # AppStore: async SQLite for app preferences
├── events.py              # UnifiedEventStream: merges Jarvis WS + health polling
└── routes/
    ├── __init__.py
    ├── jarvis.py           # /jarvis/*    — proxy to jarvis.sock (chat, stream, events WS)
    ├── policies.py         # /policies/*  — read-only proxy to policy-registry.sock
    ├── vault.py            # /vault/*     — proxy to credential-vault.sock
    ├── audit.py            # /audit/*     — proxy to intentframe.sock (audit trail)
    ├── platform.py         # /platform/*  — read-only proxy to platform.sock (health, permissions)
    ├── edi.py              # /edi/*       — EDI email account management + status
    ├── system.py           # /system/*    — health, services, lifecycle, logs, shutdown
    │                       #               includes root_demo block in /system/health response
    ├── config_routes.py    # /config/*    — app preferences CRUD
    └── events_routes.py    # /events      — unified WS + SSE event stream

intentframe_cli/
├── __init__.py
├── client.py              # GatewayClient: httpx-over-UDS, talks only to gateway.sock
├── lifecycle.py           # Start/stop gateway subprocess
└── main.py                # Interactive REPL: status, chat, logs, service mgmt, quit
```

## Endpoint Reference

### Gateway Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Gateway's own health |

### Jarvis (`/jarvis/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/jarvis/health` | Jarvis health |
| GET | `/jarvis/status` | Agent status (model, busy, tokens) |
| GET | `/jarvis/session` | Current session messages |
| POST | `/jarvis/chat` | Send a message (JSON body: `{message, client}`) |
| POST | `/jarvis/chat/stream` | Send a message, SSE streaming response |
| WS | `/jarvis/events` | Direct Jarvis event WebSocket (proxy) |

### Policies (`/policies/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/policies/` | List policies |
| GET | `/policies/{path}` | Get specific policy |

### Credential Vault (`/vault/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/vault/health` | Vault health + credential count |
| GET | `/vault/v1/credentials` | List all credentials (masked) |
| GET | `/vault/v1/credentials/{ns}` | List namespace (masked) |
| GET | `/vault/v1/credentials/{ns}/{key}` | Retrieve credential value |
| HEAD | `/vault/v1/credentials/{ns}/{key}` | Check if credential exists |
| PUT | `/vault/v1/credentials/{ns}/{key}` | Store credential |
| DELETE | `/vault/v1/credentials/{ns}/{key}` | Delete credential |
| GET | `/vault/v1/runtime-env` | Runtime env credential metadata |

### Audit (`/audit/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/audit/` | Get intent audit trail (read-only) |

### Platform (`/platform/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/platform/health` | Platform server health + TCC status |
| GET | `/platform/permissions` | macOS TCC permission status |

### EDI — Email (`/edi/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/edi/accounts` | List configured email accounts |
| POST | `/edi/accounts` | Add email account |
| DELETE | `/edi/accounts/{email}` | Remove email account |
| GET | `/edi/status` | EDI daemon status |

### System (`/system/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/system/health` | Aggregated health (all services, parallel). Response includes a `root_demo` block: `{profile, escalation_armed, sudoers_path, escalated_binary, installed_at, installer_user, marker_path, reason, executor_running_as_root}` — the CLI uses this to render the escalation banner. |
| GET | `/system/services` | Per-service status (socket, PID, health) |
| POST | `/system/{service}/start` | Start a managed service |
| POST | `/system/{service}/stop` | Stop a managed service |
| POST | `/system/{service}/restart` | Restart a managed service |
| GET | `/system/{service}/status` | Status of a managed service |
| POST | `/system/bootstrap` | Re-run policy/workspace seeding |
| POST | `/system/retry-startup` | Retry after partial startup |
| POST | `/system/shutdown` | Graceful shutdown of entire system |
| GET | `/system/logs/{service}?lines=100` | Last N log lines |
| GET | `/system/logs/{service}/stream` | SSE log tail (live streaming) |
| GET | `/system/config-env` | System config YAML + resolved env vars |
| PUT | `/system/config-env` | Set a config value (body: `{key, value}`) |
| DELETE | `/system/config-env/{key}` | Delete a config value by dotted key |

### App Config (`/config/*`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/config/` | All preferences |
| GET | `/config/{key}` | Single preference |
| PUT | `/config/{key}` | Set preference (body: `{value: any}`) |
| DELETE | `/config/{key}` | Remove preference |

### Unified Events
| Method | Path | Description |
|--------|------|-------------|
| WS | `/events` | Unified event stream (WebSocket) |
| GET | `/events/stream` | Unified event stream (SSE) |

## Caveats

### Platform Server is Opened, Not Managed

The platform server (macos-appkit-server) is launched via `open` so macOS treats it as a standalone app with its own TCC identity.  It is not a child of the gateway.  It writes its own PID file and has a `POST /shutdown` endpoint for clean teardown.

### Partial Startup Mode

If the mandatory OpenAI API key is missing from the vault, the gateway enters partial startup mode — only vault and system routes are functional.  The frontend should prompt the user to store the key via the `/vault/*` API, then restart the gateway to complete startup.  All credential management goes through the vault.

### No Authentication

All endpoints are unauthenticated.  The gateway listens on a Unix Domain Socket, which provides OS-level access control.  If ever exposed over TCP, authentication middleware must be added.
