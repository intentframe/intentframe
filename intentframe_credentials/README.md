# intentframe-credentials

Internal credential vault for the IntentFrame platform. Stores secrets in the OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service) with a lightweight SQLite sidecar for metadata, and exposes a FastAPI service over a Unix Domain Socket for trusted inter-process access.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Supervisor                          │
│  - Starts the vault service (UDS)                       │
│  - Fetches runtime_env credentials from vault           │
│  - Injects them as env vars into spawned processes      │
└────────────────────┬────────────────────────────────────┘
                     │ UDS  (/run/credential-vault.sock)
          ┌──────────▼──────────┐
          │   Vault Service     │  FastAPI + uvicorn over UDS
          │  (server.py)        │
          │                     │
          │  ┌───────────────┐  │
          │  │  OS Keyring   │  │  Secret values only
          │  │ (keyring lib) │  │
          │  └───────────────┘  │
          │  ┌───────────────┐  │
          │  │  SQLite DB    │  │  Metadata, timestamps,
          │  │ (aiosqlite)   │  │  masked previews
          │  └───────────────┘  │
          └─────────────────────┘
                     ▲
          ┌──────────┴───────────────────────┐
          │   VaultClient  (async, UDS HTTP) │
          │                                  │
          │  Callers:                        │
          │  - Supervisor  (runtime_env)     │
          │  - Executor    (via ServiceVault)│
          │  - EDI daemon  (executor_only)   │
          │  - Dashboard                     │
          │  No silent fallback              │
          └──────────────────────────────────┘
```

**Core invariant:** secret values never leave the vault service process over any transport. Agent processes (`runtime_env` credentials) receive them as environment variables injected by the supervisor. Internal platform services (`executor_only` credentials) fetch them directly via `VaultClient` at startup — the value stays in-process and is never re-serialized.

---

## Credential delivery modes

| Mode | Who reads it | How |
|---|---|---|
| `executor_only` | EDI and other trusted internal services | Fetched in-process at startup via `VaultClient`. Never injected into env vars. Never on disk. |
| `runtime_env` | Agent processes (Jarvis, external consumers, etc.) | Supervisor fetches value at spawn time, injects as an env var (e.g. `OPENAI_API_KEY`). Module reads `os.environ`. |

---

## Namespace convention

Namespaces are **dot-delimited** strings. Slashes are forbidden and are rejected at model validation time.

```python
# Correct
"openai"
"email.user@gmail.com"
"github.myorg"
"aws.prod"

# Rejected — ValidationError
"email/user@gmail.com"
```

Allowed characters: `[a-zA-Z0-9_.@+-]`, must start with a letter or digit.

---

## Package layout

```
intentframe_credentials/
├── __init__.py              # Public API re-exports
├── models.py                # Namespace, CredentialRecord, MaskedSummary, StoreRequest, DeliveryMode
├── protocol.py              # CredentialVault ABC + backend registry
├── exceptions.py            # VaultError hierarchy
├── metadata.py              # SQLite metadata store (aiosqlite)
├── redaction.py             # CredentialScrubber, SENSITIVE_KEYS
├── structlog_redactor.py    # structlog processor for log scrubbing
├── server.py                # FastAPI service (UDS transport)
├── client.py                # VaultClient (async) + VaultClientSync
└── backends/
    ├── keyring_backend.py   # OS keyring (production, used by the vault service)
    ├── service_backend.py   # ServiceVault — CredentialVault ABC backed by VaultClient over UDS
    └── env_backend.py       # env-var / in-memory (dev, CI, tests)
```

---

## Running the service

### Production (UDS, managed by supervisor)

```bash
uvicorn intentframe_credentials.server:app \
    --uds ~/.intentframe/run/credential-vault.sock
```

`INTENTFRAME_DATA_DIR` controls where `credentials.db` is written (default: `~/.intentframe/data/`).

### Development (with pre-seeded credentials)

Use the dev server script, which loads credentials from a `.env` file before starting uvicorn:

```bash
# Start over UDS (default)
uv run python -m intentframe_credentials.dev_server

# Start over TCP (easier for curl / debugging)
uv run python -m intentframe_credentials.dev_server --tcp
```

The script reads `intentframe_credentials/.env`. See `.env.example` for the expected format:

```bash
# .env — email credentials for dev/test
EMAIL_INTENTFRAME_ADDRESS=you@gmail.com
EMAIL_INTENTFRAME_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Key names map to vault entries:
# namespace = "email.<address>", key = "password"
```

Credentials loaded this way use the `EnvVault` backend (in-memory, not persisted). They exist for the lifetime of the server process only.

---

## API reference

All endpoints are served over UDS. The supervisor is the only whitelisted caller for write operations.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check with credential count |
| `GET` | `/v1/credentials` | List all credentials (masked, no values) |
| `GET` | `/v1/credentials/{namespace}` | List credentials in a namespace (masked) |
| `GET` | `/v1/credentials/{namespace}/{key}` | Retrieve a credential value |
| `HEAD` | `/v1/credentials/{namespace}/{key}` | Check existence without retrieving |
| `PUT` | `/v1/credentials/{namespace}/{key}` | Store or overwrite a credential |
| `DELETE` | `/v1/credentials/{namespace}/{key}` | Delete a credential |
| `GET` | `/v1/runtime-env` | List `runtime_env` credentials (metadata only, for supervisor) |

Secret values are **never returned** by listing endpoints. `GET /{namespace}/{key}` is the only endpoint that returns a value, and it is only accessible from trusted processes connected via UDS.

---

## Integration: EDI (email sync daemon)

EDI uses `executor_only` credentials to fetch email account passwords at config load time. Passwords are **never** stored in YAML or on disk.

**Namespace convention for email credentials:**

```
namespace = "email.<address>"
key       = "password"
```

**What EDI expects:**

1. The vault service is reachable (it pings `/health` at startup — hard-fails if not).
2. Every email address in `config.yaml` has a `password` key in the vault.
3. If either condition is not met, the daemon refuses to start.

**Storing an email password (one-time setup):**

```python
from intentframe_credentials.client import VaultClientSync
from intentframe_credentials.models import DeliveryMode

vault = VaultClientSync()
vault.store(
    "email.you@gmail.com", "password",
    value="xxxx-xxxx-xxxx-xxxx",
    delivery_mode=DeliveryMode.EXECUTOR_ONLY,
)
```

Or add it to the vault `.env` and restart the dev server.

---

## Integration: Executor

The executor uses the `service` backend by default. Its gateway fetches credentials through the `CredentialVault` ABC, which is backed by `ServiceVault` → `VaultClient` → vault service over UDS.

**How it works:**

1. Supervisor starts the vault service first
2. Supervisor starts the executor (which `depends_on: ["credential-vault"]`)
3. `executor/main.py` calls `create_credential_vault(config.credentials)` → creates `ServiceVault`
4. When an adapter declares `requires_credentials=True`, the gateway calls `vault.get(adapter_id, "api_key")`
5. That goes over UDS to the vault service

**Executor config (`executor.yaml`):**

```yaml
credentials:
  backend: service    # talks to the vault service over UDS
  options: {}
```

The executor's `CredentialVault`, `CredentialScrubber`, and `SENSITIVE_KEYS` are all re-exported from this package via thin shims — zero executor code was changed, only the backing implementation was replaced.

---

## Client usage

### Async (supervisor, executor, dashboard)

```python
from intentframe_credentials.client import VaultClient

async with VaultClient() as vault:
    # Store
    await vault.store(
        "openai", "api_key",
        value="sk-proj-...",
        delivery_mode=DeliveryMode.RUNTIME_ENV,
        env_name="OPENAI_API_KEY",
    )

    # Retrieve
    key = await vault.get("openai", "api_key")

    # List
    summaries = await vault.list_all()          # masked, dashboard-safe
    runtime = await vault.list_runtime_env()    # for supervisor spawn
```

The socket path defaults to `~/.intentframe/run/credential-vault.sock` or the `INTENTFRAME_VAULT_SOCKET` env var.

### Sync (CLI tools, one-off scripts)

```python
from intentframe_credentials.client import VaultClientSync

vault = VaultClientSync()
vault.store("github.myorg", "token", value="ghp_...")
token = vault.get("github.myorg", "token")
```

`VaultClientSync` uses `asyncio.run()` per call — do not use from within a running event loop.

---

## Backends

### `service` (default for consumers)

`ServiceVault` implements the `CredentialVault` ABC by delegating to `VaultClient` over UDS. This is the backend used by the executor, and any other module that needs the ABC interface to talk to the running vault service.

```python
from intentframe_credentials.protocol import create_vault

vault = create_vault("service")
value = await vault.get("openai", "api_key")  # → HTTP GET to vault service
```

The executor uses this automatically — `executor.yaml` sets `credentials.backend: service`, and the executor gateway calls `vault.get(...)` through the ABC without knowing it goes over UDS.

### `keyring` (used by the vault service internally)

Delegates to the OS keyring library. Auto-detected backend:

- **macOS** — Keychain (AES-256, tied to user login)
- **Windows** — Credential Manager (DPAPI)
- **Linux** — Secret Service (GNOME Keyring / KDE Wallet)

Service name format: `com.intentframe.vault.<namespace>`

### `env` (dev, CI, testing)

Reads from `os.environ` using the convention `<NAMESPACE>_<KEY>` (upper-cased, dots and dashes replaced with underscores). Writes go to an in-memory overlay only — nothing is persisted.

```python
# OPENAI_API_KEY in env → get("openai", "api_key")
# GITHUB_MYORG_TOKEN in env → get("github.myorg", "token")
```

---

## Redaction

`CredentialScrubber` and the `redact_credentials` structlog processor scrub sensitive fields from dicts and log events. Configure structlog once at startup:

```python
import structlog
from intentframe_credentials import redact_credentials

structlog.configure(
    processors=[
        redact_credentials,
        structlog.processors.JSONRenderer(),
    ]
)
```

Fields matching `SENSITIVE_KEYS` (e.g. `password`, `api_key`, `token`, `secret`) are replaced with `[REDACTED]` before any log output.

---

## Exception hierarchy

```
VaultError
├── CredentialNotFoundError   # credential does not exist
├── CredentialStoreError      # failed to persist to backend
├── CredentialDeleteError     # failed to remove from backend
├── ValidationFailedError     # external service rejected the credential
├── BackendUnavailableError   # keyring / service unreachable
└── MetadataStoreError        # SQLite read/write failure
```

---

## Development

```bash
# Install with dev extras
uv sync --extra dev

# Run tests
uv run pytest

# Start the dev vault (seeded from .env)
uv run python -m intentframe_credentials.dev_server

# Use the env backend directly in tests (no server needed)
from intentframe_credentials.backends.env_backend import EnvVault
from intentframe_credentials.protocol import create_vault

vault = create_vault("env")
await vault.store("openai", "api_key", "sk-test-...")
```

### Smoke-testing the vault

```bash
# Health check
curl --unix-socket ~/.intentframe/run/credential-vault.sock http://localhost/health

# Check a credential exists
curl --unix-socket ~/.intentframe/run/credential-vault.sock \
    -X HEAD http://localhost/v1/credentials/email.you@gmail.com/password

# Fetch a value
curl --unix-socket ~/.intentframe/run/credential-vault.sock \
    http://localhost/v1/credentials/email.you@gmail.com/password
```

With `--tcp`, replace the socket arguments with `http://localhost:8765/...`.
