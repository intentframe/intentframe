# The Credentials Vault

> Where every IntentFrame secret lives, how it gets to the process that needs it, and why no other process can touch it.

The credentials vault is the single source of truth for every secret IntentFrame uses — your OpenAI API key, your IMAP/SMTP passwords, your Telegram bot token, OAuth tokens for adapter integrations. Other processes ask the vault for what they need; the vault decides whether to answer; secrets travel only as far as the requesting process and never get logged, serialized, or written to plaintext disk.

This document covers the vault from a user / operator / integrator perspective. For the implementation reference (API surface, backend list, async client usage), see [`../intentframe_credentials/README.md`](../intentframe_credentials/README.md).

---

## What it is

A standalone process that runs alongside the rest of IntentFrame, exposes a small HTTP API over a Unix domain socket, and stores actual secret values in a pluggable backend — the OS keyring on a workstation (macOS Keychain, Windows Credential Manager, Linux Secret Service), or a HashiCorp Vault for headless/cloud deployments (see [Backends](#backends)).

```
┌──────────────────────────────────────────────────────────────┐
│              CREDENTIAL VAULT (process)                       │
│  intentframe_credentials/server.py                            │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  FastAPI service over UDS                               │ │
│  │  ~/.intentframe/run/credential-vault.sock               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌──────────────────────┐    ┌──────────────────────────────┐│
│  │  OS Keyring          │    │  SQLite metadata sidecar      ││
│  │  (macOS Keychain,    │    │  ~/.intentframe/data/         ││
│  │   Credential Mgr,    │    │    credentials.db             ││
│  │   Secret Service)    │    │  Stores: namespace, key,      ││
│  │  Stores: secret      │    │    masked preview, timestamps,││
│  │    values only       │    │    delivery mode (NO values)  ││
│  └──────────────────────┘    └──────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
                          ▲
                          │ Unix domain socket only
                          │ (no TCP, no network)
                          │
        ┌─────────────────┼─────────────────────────┐
        │                 │                         │
   ┌────▼─────┐    ┌──────▼──────┐         ┌────────▼────────┐
   │  Gateway │    │   Executor  │         │  EDI            │
   │  (reads  │    │   (Service- │         │  (executor_only │
   │  runtime │    │    Vault    │         │   credentials   │
   │  env at  │    │    backend) │         │   for IMAP/SMTP)│
   │  spawn)  │    │             │         │                 │
   └──────────┘    └─────────────┘         └─────────────────┘
```

**Core invariant:** secret values never leave the vault service process over any transport. Other processes get them in one of two ways (see "Delivery modes" below), and each delivery mode is designed so the value lands in the requesting process's memory and is never re-serialized.

---

## What lives in it

| Secret | Stored as | Used by | Delivery mode |
|---|---|---|---|
| OpenAI API key | `namespace="openai", key="api_key"` | `intentframe-core` (AE + Guardian), `jarvis` (agent reasoning) | `runtime_env` → `OPENAI_API_KEY` |
| IMAP/SMTP password | `namespace="email.<address>", key="password"` | `email-sync-daemon` | `executor_only` |
| Telegram bot token | `namespace="telegram", key="bot_token"` | `jarvis-telegram` | `runtime_env` |
| OAuth tokens (Slack, GitHub, etc.) | `namespace="<service>", key="token"` | `executor` adapters | `executor_only` |
| Custom service credentials | Whatever the integration declares | The integrating process | Configurable |

The vault doesn't care what the namespaces mean — they're just dot-delimited strings that organize credentials. Convention is one namespace per service.

---

## Delivery modes

There are two ways a credential gets from the vault into a process. The choice is made when the credential is stored and is enforced for its lifetime.

### `runtime_env` — for agent-process credentials

The supervisor fetches the value at spawn time and injects it as an environment variable. The child process reads it from `os.environ` at startup.

```
1. Supervisor about to spawn intentframe-core
2. Supervisor calls vault.list_runtime_env()  → ["openai/api_key", ...]
3. Supervisor calls vault.get("openai", "api_key")  → "sk-proj-..."
4. Supervisor sets OPENAI_API_KEY in the spawned process's env
5. intentframe-core reads os.environ["OPENAI_API_KEY"] at startup
6. The OpenAI client is built once with that key, in-process
7. The vault is never re-queried for this credential
```

Used for: OpenAI key (needed by `intentframe-core`, `jarvis`, `onboarding`), Telegram bot token (needed by `jarvis-telegram`).

### `executor_only` — for trusted internal services

The consuming service connects to the vault directly over UDS at startup or at first use, fetches the value, and holds it in memory only. No environment variable, never on disk.

```
1. EDI daemon starts up, loads its config
2. For each email account, EDI calls vault.get("email.<address>", "password")
3. Each value goes into a pydantic.SecretStr field on AccountConfig
4. The IMAP connection unwraps it at the boundary: account.password.get_secret_value()
5. If anything tries to repr(), log, or serialize the AccountConfig, it sees "**********"
```

Used for: IMAP/SMTP passwords (EDI), executor adapter credentials (`ServiceVault` backend).

### Why two modes?

**`runtime_env` is simpler** — child processes don't need to know the vault exists. They just read an env var. But environment variables are visible in `ps`, `/proc/<pid>/environ` (on Linux), and any tooling that dumps process state. So they're appropriate for credentials that the process holds for its entire lifetime anyway (the OpenAI key isn't a secret per request — it's a per-process bootstrap).

**`executor_only` keeps the value off the environment**, at the cost of requiring the consumer to talk to the vault. It's used for credentials that are sensitive enough to keep out of the env, and for cases where the consumer can wrap them in `SecretStr` and never let them surface in logs or tracebacks.

---

## How a credential gets there

There are three ways a credential ends up in the vault.

### 1. Setup-time, via the gateway prompt

On first launch, the gateway checks for the OpenAI key. If it's missing, the gateway enters partial-startup mode and prints the command to add it:

```
[setup] Mandatory credential missing: openai/api_key
[setup] Run: vault set openai api_key <YOUR_KEY>
[setup] Then restart the gateway.
```

You run that command, restart, and the key is now in the OS keyring under `com.intentframe.vault.openai`.

### 2. Dev-time, via the dev-server `.env`

For development, you can pre-seed credentials by putting them in `intentframe_credentials/.env`. The dev-server reads that file at startup and loads them into an in-memory backend:

```bash
# intentframe_credentials/.env
OPENAI_API_KEY=sk-proj-...
EMAIL_WORK_ADDRESS=you@gmail.com
EMAIL_WORK_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

```bash
uv run python -m intentframe_credentials.dev_server
```

Dev-mode credentials live for the lifetime of the dev server only. They're not persisted to the OS keyring.

### 3. Programmatically, via the client

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

This goes into the production keyring backend if the vault service is running.

---

## How a credential gets out

A consumer can ask the vault for any credential it has access to. There is exactly one endpoint that returns a secret value (`GET /v1/credentials/{namespace}/{key}`); everything else returns metadata only.

```python
from intentframe_credentials.client import VaultClient

async with VaultClient() as vault:
    key = await vault.get("openai", "api_key")
    # key is now a string in this process's memory
    # the vault has no further role until next get()
```

The vault listens only on a Unix domain socket in `~/.intentframe/run/credential-vault.sock`. Filesystem permissions on that socket are the access control. There is no network exposure.

---

## What's protected, what isn't

### Protected

- **Plaintext on disk:** secret values are in the OS keyring, which is encrypted (AES-256 on macOS, DPAPI on Windows). Nothing is in `~/.intentframe/data/credentials.db` except metadata (namespace, key, masked preview, timestamps, delivery mode).
- **Process-boundary leakage:** secret values are never serialized in API responses (only `GET /v1/credentials/{ns}/{key}` returns a value, and only over UDS). Listing endpoints return masked previews.
- **Log leakage:** `intentframe_credentials.redaction.redact_credentials` is a structlog processor wired into every IntentFrame service. Any field matching `SENSITIVE_KEYS` (`password`, `api_key`, `token`, `secret`, etc.) is replaced with `[REDACTED]` before output.
- **Traceback leakage:** consumers wrap values in `pydantic.SecretStr`, so `repr()` and tracebacks show `SecretStr('**********')` instead of the value. Code that uses the secret unwraps with `.get_secret_value()` only at the IMAP / SMTP / API call site.
- **Network exposure:** UDS only. Nothing listens on a TCP port. There is no path for a remote process to reach the vault.

### Not protected

- **Local root or your user account:** if an attacker is already running as your user, they can read your keyring. The vault is not a defense against local compromise — it's a defense against credential leakage *within* a healthy IntentFrame stack (logs, agent processes, sub-processes).
- **Process memory dumps:** any process that has fetched a credential holds it in memory for its lifetime. A debugger attached to that process can read it. This is unavoidable for any system that uses secrets.
- **Environment-variable visibility:** `runtime_env` credentials are visible in `ps eww`, `/proc/<pid>/environ`, and similar tooling for the lifetime of the receiving process. If you want a credential off the env entirely, mark it `executor_only` (and have the consumer fetch it via `VaultClient`).
- **At-rest disk encryption of metadata:** the SQLite metadata sidecar (`~/.intentframe/data/credentials.db`) is plaintext. It has no values, but it has the namespace/key inventory. Use FileVault / LUKS for at-rest protection.

---

## Who can read what

The vault doesn't currently enforce per-process ACLs — any process that can connect to the socket can call any endpoint. The defense-in-depth posture is:

1. **Filesystem permissions on the socket** restrict who can connect (your user's processes only).
2. **Process model**: only IntentFrame's own services normally have a reason to connect.
3. **Convention**: the supervisor is the only writer for `runtime_env` credentials; consumers only read what they need.

A future enhancement is per-caller authentication on the vault socket (so the executor cannot read a credential intended for the gateway, even though both are local). It is not shipped today; it's noted in the implementation README.

---

## Lifecycle

```
GATEWAY STARTS
    └─ Step 1: starts the credential-vault process
              (uvicorn intentframe_credentials.server:app
               --uds ~/.intentframe/run/credential-vault.sock)
    └─ Step 2: gateway calls vault.get("openai", "api_key")
              to gate further startup. If missing → partial-startup mode.
    └─ Step 4: supervisor builds runtime_env from
              vault.list_runtime_env() + vault.get(...) for each
    └─ Step 6: supervisor spawns 4 services with that env
              (each child reads what it needs from os.environ)

EXECUTOR STARTS (under supervisor)
    └─ executor.yaml: credentials.backend = service
    └─ executor builds ServiceVault (a CredentialVault ABC backed by VaultClient)
    └─ When an adapter declares requires_credentials=True,
       the gateway calls vault.get(adapter_id, "api_key") through ServiceVault
       → goes over UDS to the vault service

EDI STARTS (under gateway)
    └─ EDI loads config.yaml (email addresses only)
    └─ For each address, EDI calls vault.get("email.<address>", "password")
    └─ Each password becomes a SecretStr field on AccountConfig
    └─ IMAP / SMTP unwraps with .get_secret_value() at the boundary

GATEWAY STOPS
    └─ All children stopped (in reverse order)
    └─ vault service stopped last
    └─ secret values disappear from every process's memory
```

Source of truth: `intentframe_gateway/server.py` (lifespan, steps 1–6); `intentframe_credentials/server.py` (vault service); `intentframe_credentials/client.py` (`VaultClient`, `VaultClientSync`); `external_data_ingestion/external_data_ingestion/email/config.py` (EDI integration).

---

## API surface (over UDS)

| Method | Path | Description | Returns value? |
|---|---|---|---|
| `GET` | `/health` | Health + credential count | No |
| `GET` | `/v1/credentials` | All credentials (masked) | No |
| `GET` | `/v1/credentials/{namespace}` | One namespace (masked) | No |
| `GET` | `/v1/credentials/{namespace}/{key}` | Retrieve a credential value | **Yes — only endpoint that does** |
| `HEAD` | `/v1/credentials/{namespace}/{key}` | Check existence | No |
| `PUT` | `/v1/credentials/{namespace}/{key}` | Store or overwrite | No |
| `DELETE` | `/v1/credentials/{namespace}/{key}` | Delete | No |
| `GET` | `/v1/runtime-env` | List `runtime_env` creds (metadata only, for supervisor) | No |

For full client usage examples, see [`../intentframe_credentials/README.md`](../intentframe_credentials/README.md).

---

## Backends

The vault service uses one of these backends to physically store values. The service selects its storage backend from the `IF_VAULT_BACKEND` environment variable (default `keyring`).

| Backend | When | What it does |
|---|---|---|
| `keyring` | Production on a workstation (default) | Delegates to OS keyring (macOS Keychain / Windows Credential Manager / Linux Secret Service). Service name format: `com.intentframe.vault.<namespace>` |
| `hashicorp` | Headless / cloud / on-prem | Stores secrets in a HashiCorp Vault KV v2 engine over HTTP. Use this where the OS keyring isn't available (cloud servers, containers, Kubernetes). Configured via `VAULT_*` env vars; supports AppRole auth with automatic token renewal |
| `service` | Default for *consumers* (executor, dashboard) | `ServiceVault` — implements the `CredentialVault` ABC by calling `VaultClient` over UDS. Lets the executor's gateway call `vault.get(...)` without knowing the value lives in another process |
| `env` | Dev / CI / testing | Reads `os.environ` using `<NAMESPACE>_<KEY>` convention. In-memory writes only — nothing is persisted |

The keyring backend is what the production vault service uses on a workstation. The hashicorp backend is the headless-friendly replacement for cloud deployments. The service backend is what the executor uses to talk to the vault. The env backend is what tests use to skip the whole vault layer.

### Headless / cloud deployments (HashiCorp Vault)

The OS keyring doesn't exist on a typical headless cloud server, so for those deployments point the vault service at a HashiCorp Vault instead:

```bash
export IF_VAULT_BACKEND=hashicorp
export VAULT_ADDR=https://vault.mycorp.com:8200
export VAULT_ROLE_ID=...        # AppRole, preferred for long-running services
export VAULT_SECRET_ID=...
```

Everything else — the UDS service, delivery modes, metadata DB, CLI, and the `service` backend used by consumers — is unchanged; only where the values physically live changes. The backend keeps its Vault token alive with a renewal loop (and re-logs in via AppRole when the token's max TTL is reached). Full setup, policy, and local Docker testing instructions are in the implementation README: [`../intentframe_credentials/README.md`](../intentframe_credentials/README.md#hashicorp-headless--cloud--on-prem).

#### Deployment wiring — where the config actually goes

Switching to HashiCorp is a **single-place change**, not a per-module one. The credential-vault service is started by the **gateway**, and it inherits the gateway's environment:

```
gateway process environment  (systemd unit / container env / shell)
   │  os.environ  ──────────────────────────────────────────┐
   │                                                         ▼
   └─ ProcessManager.start_vault()  ──spawns──►  credential-vault service
                                                  (intentframe_credentials.server:app)
                                                     │ reads IF_VAULT_BACKEND
                                                     │ backend reads VAULT_*
                                                     ▼
                                                  HashiCorp Vault (KV v2)
```

So you set `IF_VAULT_BACKEND` + `VAULT_*` once, in the gateway's launch environment. From there:

| Component | Change needed | Why |
|---|---|---|
| **Gateway environment** | Set `IF_VAULT_BACKEND=hashicorp`, `VAULT_ADDR`, `VAULT_ROLE_ID`, `VAULT_SECRET_ID` | The gateway propagates `os.environ` to the vault service it spawns. This is the single source of truth. |
| **`intentframe_credentials`** | Install the extra (`uv sync --extra hashicorp`) | Needs `hvac`. There is no config file — the backend is **env-selected**, not file-configured. |
| **Supervisor** | Nothing | It doesn't start the vault. It only propagates env to *its* children (executor, core), which reach the vault over UDS and never need `VAULT_*`. |
| **Executor (`executor.yaml`)** | Nothing — keep `credentials.backend: service` | The executor talks to the vault **service over UDS** via `ServiceVault`. It never talks to HashiCorp directly; the service does the persisting. |

The two settings that look alike but mean different things:

- **`IF_VAULT_BACKEND`** (env var, read by the vault *service*) = *where secrets physically live* → set to `hashicorp`.
- **`credentials.backend` in `executor.yaml`** (read by *consumers*) = *how a consumer reaches the vault* → keep `service` (UDS).

You only flip the first. The `hashicorp` value also accepted by `executor.yaml`'s `credentials.backend` exists only for the unusual case of a consumer bypassing the service and hitting Vault directly — not the normal deployment.

> **Use AppRole, not a static token, for the gateway.** `VAULT_TOKEN` takes precedence over AppRole in the backend, and a static token can't be re-issued when it expires. Set only `VAULT_ROLE_ID` / `VAULT_SECRET_ID` so the renewal loop can keep the long-running session alive.

---

## Quick answers

| Question | Answer |
|---|---|
| Where is my OpenAI key stored? | macOS Keychain entry `com.intentframe.vault.openai` (account `api_key`). |
| Where are my IMAP passwords stored? | macOS Keychain entry `com.intentframe.vault.email.<address>` (account `password`). |
| Can I see my secrets via `intentframe-cli`? | The vault doesn't expose a "show me my secrets" endpoint by design. You can confirm a credential exists (`HEAD /v1/credentials/{ns}/{key}`); you can't list values. |
| What if I delete `~/.intentframe/data/credentials.db`? | You lose the metadata inventory. Values are still in the keyring; you'd have to re-store them via the vault to repopulate metadata. |
| What if I remove the keyring entries? | The vault has no values. Mandatory-credential gating will refuse to start dependent services. You re-store them via the gateway setup flow or `VaultClientSync.store(...)`. |
| Does the vault talk to the network? | No. UDS only. |
| Does the vault encrypt values itself? | No — it relies on the OS keyring for at-rest encryption. The keyring backends use platform-native cryptography (AES-256 on macOS, DPAPI on Windows). |
| Can two IntentFrame instances share a vault? | One vault per `~/.intentframe/run/` socket directory. If you want two instances, give them separate `INTENTFRAME_RUN_DIR` paths. |
| Can I rotate a credential without restarting? | Update via `PUT /v1/credentials/{ns}/{key}`. `runtime_env` credentials are baked into a process's env at spawn time, so those processes need to restart to pick up the new value. `executor_only` consumers may pick it up on next `vault.get()` if they don't cache. |

---

## Documented gaps

- **No per-caller ACL on the vault socket.** All processes that can connect can call any endpoint. Filesystem permissions are the only barrier. Fine on a single-user device; needs caller-attested auth for multi-tenant or shared-host deployments.
- **No automatic credential rotation.** Rotation is manual (re-store and restart consumers).
- **No HSM / KMS backend yet.** The `keyring` backend covers OS-managed encryption on a workstation, and the `hashicorp` backend covers headless/cloud storage via HashiCorp Vault (which provides its own at-rest encryption). A direct cloud-native `aws-kms` / GCP / Azure Key Vault backend is not shipped.
- **Metadata SQLite is plaintext.** Use FileVault / LUKS for at-rest protection of the metadata inventory.

---

## Related documents

- [`../intentframe_credentials/README.md`](../intentframe_credentials/README.md) — Implementation reference: full API, backends, client usage, exception hierarchy, redaction
- [processes.md](processes.md) — Where the vault sits in the process tree
- [privacy.md](privacy.md) — Where each kind of secret lives and what scrubbing protects against
- [executor.md § 5. Credential isolation](executor.md#5-credential-isolation) — Why the executor (which holds adapter credentials) is structurally separated from the rest of the pipeline
- [email-sync.md](email-sync.md) — How EDI gets its IMAP/SMTP passwords from the vault
