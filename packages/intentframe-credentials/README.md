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

PyPI: [intentframe-credentials](https://pypi.org/project/intentframe-credentials/) · `pip install intentframe-credentials==0.1.0` · License: Apache-2.0 · [Consumer guide](../../docs/package-consumers.md)

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

### `hashicorp` (headless / cloud / on-prem)

Stores secrets in a HashiCorp Vault KV v2 engine over its HTTP API. Use this on headless servers where the OS keyring is unavailable (no Keychain / GNOME Keyring daemon). Works on any cloud, bare metal, or Kubernetes that can reach a Vault.

Install with the extra:

```bash
pip install 'intentframe-credentials[hashicorp]'   # or: uv sync --extra hashicorp
```

**Storage layout.** Each IntentFrame *namespace* maps to one KV v2 secret at `<prefix>/<namespace>`, and each *key* is a field within that secret. This mirrors how the keyring backend groups credentials and lets `list_keys` work natively. Example: `email.you@gmail.com` → secret `intentframe/email.you@gmail.com` with fields `password`, `username`.

**Configuration — all via env vars (no code changes):**

| Env var | Purpose |
|---|---|
| `VAULT_ADDR` | Vault address, e.g. `https://vault.mycorp.com:8200` (required) |
| `VAULT_TOKEN` | Static token (auth option A) — **takes precedence over AppRole** |
| `VAULT_ROLE_ID` / `VAULT_SECRET_ID` | AppRole login (auth option B, preferred for long-running services) |
| `VAULT_NAMESPACE` | Vault Enterprise namespace (optional) |
| `VAULT_KV_MOUNT` | KV v2 mount point (default `secret`) |
| `VAULT_PATH_PREFIX` | Path prefix (default `intentframe`) |
| `VAULT_RENEW` | Token renewal loop on/off (default `true`) |

Every option can also be passed to the constructor (`HashiCorpVault(addr=..., role_id=...)`), and constructor options take precedence over env vars.

**Selecting the backend.** The vault **service** chooses its storage backend from `IF_VAULT_BACKEND` (default `keyring`). Set it to `hashicorp` to run the service against Vault:

```bash
export IF_VAULT_BACKEND=hashicorp
export VAULT_ADDR=http://127.0.0.1:8200
export VAULT_ROLE_ID=...        # or VAULT_TOKEN=... for a quick test
export VAULT_SECRET_ID=...
uv run uvicorn intentframe_credentials.server:app --uds ~/.intentframe/run/credential-vault.sock
```

Consumers (executor, dashboard) keep using the `service` backend over UDS exactly as before — only the service's persistence changed.

#### Token renewal

`hvac` does **not** renew tokens automatically; it only exposes one-shot `renew_self` / `login` calls. The backend runs its own async loop that:

1. Looks up the token TTL; if the token has no expiry (e.g. a root/dev token) it stops — nothing to do.
2. Sleeps until ~half the TTL has elapsed, then calls `renew_self`.
3. If the token isn't renewable (hit `token_max_ttl`) or renewal fails, it falls back to an **AppRole re-login** (`role_id` + `secret_id`) to mint a fresh token. A static token with no AppRole and no recovery path stops the loop with a logged error.

The loop starts lazily on first use and is cancelled on `close()` (the service calls this on shutdown). Disable it with `VAULT_RENEW=false`.

> For an effectively non-expiring service token, configure the role with `token_period` (periodic tokens renew indefinitely and never hit a max-TTL cap). Using `token_max_ttl` instead is fine — the backend recovers via re-login — but you'll see a one-line renewal-failure warning each time the cap is reached.

#### Production AppRole setup

Create a scoped policy (KV v2 splits *data* and *metadata* paths; `renew-self`/`lookup-self` come from the built-in `default` policy):

```hcl
# intentframe-policy.hcl
path "secret/data/intentframe/*" {
  capabilities = ["create", "update", "read", "delete"]
}
path "secret/metadata/intentframe/*" {
  capabilities = ["read", "list", "delete"]
}
```

```bash
vault policy write intentframe intentframe-policy.hcl
vault auth enable approle
vault write auth/approle/role/intentframe \
    token_policies=intentframe \
    token_ttl=1h token_max_ttl=4h    # or: token_period=1h for indefinite renewal

# Fetch the credentials your service will use as VAULT_ROLE_ID / VAULT_SECRET_ID:
vault read   auth/approle/role/intentframe/role-id
vault write -f auth/approle/role/intentframe/secret-id
```

#### Local testing with Docker

Helper scripts live in [`scripts/`](scripts/). They spin up a dev Vault, configure a short-lived AppRole, and exercise the backend.

```bash
# 1. Recreate a dev Vault + configure AppRole (token_ttl=20s, token_max_ttl=60s).
#    `eval` also exports VAULT_ADDR / VAULT_ROLE_ID / VAULT_SECRET_ID into your shell.
eval "$(./scripts/vault_dev_setup.sh)"
unset VAULT_TOKEN     # ensure AppRole (not a leftover static token) is used

# 2. CRUD smoke test — runs the full store/get/has/list/delete contract.
uv run python scripts/vault_smoke_test.py

# 3. Renewal demo — watch the token renew every ~10s and re-login at the 60s cap.
uv run python scripts/vault_renewal_demo.py --seconds 80

# 4. (optional) pytest integration suite — skipped automatically unless VAULT_ADDR is set.
uv run pytest tests/test_hashicorp_backend.py -v
```

Manual one-liner if you'd rather not use the setup script (root token, no AppRole — the renewal loop will no-op since root tokens don't expire):

```bash
docker run -d --name vault-dev --cap-add=IPC_LOCK -p 8200:8200 \
    -e VAULT_DEV_ROOT_TOKEN_ID=dev-root-token hashicorp/vault:latest

export VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=dev-root-token
uv run python scripts/vault_smoke_test.py
```

Inspect what got written from the other side:

```bash
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=dev-root-token \
    vault-dev vault kv get secret/intentframe/<namespace>
# or open the UI at http://127.0.0.1:8200 (token: dev-root-token)
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
