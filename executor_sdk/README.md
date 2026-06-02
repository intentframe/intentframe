# IntentFrame Executor SDK

Contract layer for **executor packs** — the plugins that supply capability
adapters and (optionally) platform backends (transport, auth, storage) to the
`executor` host process.

First-party reference packs live under
[`intentframe_native_kit/`](../intentframe_native_kit/) (`intentframe_executor_pack_posix`,
`intentframe_executor_pack_macos`, `intentframe_executor_pack_console`).

---

## What this package is (and is not)

| Layer | Owns | Must not |
|-------|------|----------|
| **`executor/`** | Gateway, dispatch, worker pool, config loading, pack loader, startup wiring | Be imported by pack code |
| **`executor_sdk/`** (this package) | ABCs, wire models, plugin registries, pack registration helpers | Import `executor/` |
| **Executor packs** | Adapter and/or platform implementations | Import `intentframe_core` or `executor/` directly |

Packs run **in-process** with full Python access. Registration via
`register_*()` is a **wiring contract**, not a security boundary. Treat
third-party packs as trusted code unless you add an out-of-process isolation
layer.

The executor ships **no built-in packs**. `executor.yaml` must list at least
one pack under `packs:` or startup fails (fail-closed).

---

## Three author roles (do not collapse these)

1. **Adapter author** — implements `CapabilityAdapter` for one or more action
   types (`SEND_EMAIL`, `READ_FILE`, …). This is what most third-party pack
   authors care about.
2. **Platform author** — implements executor backends so the host can boot:
   transport, auth verifier, audit logger, state store, optional credential
   vault alias, virtual filesystem. The posix pack is the minimal platform base.
3. **Executor host** — `executor/` consumes registered implementations via
   `create_*` factories and runs the gateway pipeline. Pack authors normally
   never import `executor/`.

A single distribution may combine platform + adapter code (as the native kit
does), but the **contracts are different tiers**.

---

## Minimum deployment

To run the executor meaningfully today:

```yaml
# executor.yaml
packs:
  - intentframe_native_kit.intentframe_executor_pack_posix   # platform base
  - intentframe_native_kit.intentframe_executor_pack_macos     # optional: native adapters

adapters:
  enabled:
    - files
    - mail
```

| Config empty? | Result |
|---------------|--------|
| `packs: []` | Startup fails — no transport/auth/storage registered |
| Packs loaded, `adapters.enabled: []` | Executor boots but rejects every action (no adapter routing) |

Credential backends (`service`, `keyring`, `env`, `hashicorp`) self-register when
`executor_sdk.services.credential_vault` is imported during executor startup;
selection is via `credentials.backend` in config, not pack registration.

---

## Pack contract

Every pack exposes a module-level callable (no registration on import):

```python
def register_all() -> None:
    """Register this pack's implementations. Must be idempotent."""
    ...
```

Discovery for installed distributions:

```toml
# pyproject.toml
[project.entry-points."intentframe.executor_packs"]
acme = "acme_intentframe_pack:register_all"
```

Constant: `executor_sdk.packs.ENTRY_POINT_GROUP` → `"intentframe.executor_packs"`.

The executor loads packs once at startup (`executor/server.py` →
`_register_packs()` → `register_all()` on each entry), then calls
`executor/main.py` → `build_gateway()` to instantiate components from config.

---

## Registration pattern

Each swappable component uses the same pattern:

| Step | Who | What |
|------|-----|------|
| 1 | Pack | `register_*(key, Class)` writes into a module-level registry dict |
| 2 | Config | `executor.yaml` selects the key (`transport.type`, `auth.type`, …) |
| 3 | Executor | `create_*(config)` reads the registry and constructs the instance |

Example (adapter):

```python
from executor_sdk.adapters import register_adapter

register_adapter("mail", MailAdapter)
```

```yaml
adapters:
  enabled:
    - mail
```

The executor then calls `create_adapter("mail", credential_vault=..., pack_options=...)`.

`register_*` functions are **public pack-author API**. The underlying
`_ADAPTER_REGISTRY` (and sibling private dicts) are implementation details,
though any in-process code can still reach them — there is no sandbox.

---

## Package layout

```
executor_sdk/
  __init__.py              owner_home (re-export from intentframe_core)
  packs.py                 ENTRY_POINT_GROUP, pack contract docs
  models.py                Wire models and enums
  constants.py             Timeouts, paths, audit/hash defaults
  exceptions.py            ExecutorError hierarchy
  adapters/
    base.py                CapabilityAdapter (+ safe_execute / safe_rollback)
    __init__.py            register_adapter, create_adapter
  auth/
    base.py                AuthVerifier
    __init__.py            register_auth_verifier, create_auth_verifier
  transport/
    base.py                TransportServer, RequestHandler
    __init__.py            register_transport, create_transport
  services/
    audit_logger.py        AuditLogger, register/create audit logger
    state_store.py         StateStore, register/create state store
    credential_vault.py    CredentialVault + backend re-exports, register/create
    credential_scrubber.py CredentialScrubber (gateway; re-export)
    hash_chain.py          HashChain (audit integrity)
    virtual_filesystem.py  VirtualFileSystem, MountPointResolver, MountPointConfig
```

---

## Import surface by role

### Adapter author (typical third-party pack)

Only these are required for a non-filesystem adapter:

```python
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult
from executor_sdk.adapters import register_adapter
```

Filesystem / VFS adapters additionally use:

```python
from executor_sdk.exceptions import VirtualFileSystemError
from executor_sdk.services.virtual_filesystem import MountPointConfig, expand_path
```

Adapters receive `(action, params, credentials)` from the gateway — **not**
`ExecutionRequest`. Optional constructor kwargs from the executor:
`credential_vault`, `pack_options` (opaque slice from `executor.yaml`).

### Platform author (posix / custom deployment base)

Everything in the adapter tier, plus backends and their registration:

| Module | Register | ABC | Config key |
|--------|----------|-----|------------|
| `executor_sdk.transport` | `register_transport` | `TransportServer` | `transport.type` |
| `executor_sdk.auth` | `register_auth_verifier` | `AuthVerifier` | `auth.type` |
| `executor_sdk.services.audit_logger` | `register_audit_logger` | `AuditLogger` | `storage.audit_backend` |
| `executor_sdk.services.state_store` | `register_state_store` | `StateStore` | `storage.state_backend` |
| `executor_sdk.services.credential_vault` | `register_credential_vault` | `CredentialVault` | `credentials.backend` |
| `executor_sdk.services.virtual_filesystem` | — | `VirtualFileSystem` | via files adapter / pack |

Platform implementations also use wire models from `executor_sdk.models`, e.g.
`ExecutionRequest`, `AuthorizationProof`, `AuthResult`, `AuditEntry`,
`SecurityEvent`, `RollbackEntry`, `ExecutionStatus`.

Path helper used by platform code:

```python
from executor_sdk import owner_home
```

### Executor host only (pack authors should not need these)

These live in `executor_sdk` today because the host imports them; they are
**not** part of the adapter-author contract:

| Symbol | Used by |
|--------|---------|
| `create_adapter`, `create_transport`, `create_auth_verifier`, … | `executor/main.py` startup |
| `CredentialScrubber` | `executor/gateway.py` (scrub before audit) |
| `HashChain` | Gateway stamps audit entries; storage backends may verify |
| `AdapterNotFoundError`, `RequestValidationError` | Dispatch / gateway |
| Most `constants.py` entries | `executor/config`, worker pool, hash chain |
| `RequestMetadata`, `SecurityEventType` | Gateway / transport wire path |

Future refactors may move host-only symbols under `executor/` and leave
`executor_sdk` as contracts + `register_*` only.

---

## Extension points (registry-backed)

| Key in config | Registry function | ABC |
|---------------|-------------------|-----|
| `adapters.enabled[]` | `register_adapter` | `CapabilityAdapter` |
| `transport.type` | `register_transport` | `TransportServer` |
| `auth.type` | `register_auth_verifier` | `AuthVerifier` |
| `storage.audit_backend` | `register_audit_logger` | `AuditLogger` |
| `storage.state_backend` | `register_state_store` | `StateStore` |
| `credentials.backend` | backends self-register; optional `register_credential_vault` | `CredentialVault` |

Only **one** transport and **one** auth verifier are active per executor
instance. Adapters are many; each action type must map to exactly one adapter
globally.

---

## Models (`executor_sdk.models`)

| Model / enum | Adapter author | Platform author | Executor host |
|--------------|----------------|-----------------|---------------|
| `AdapterManifest`, `ExecutionResult` | yes | yes | yes |
| `AuthorizationProof`, `AuthResult` | — | auth impl | gateway |
| `ExecutionRequest`, `RequestMetadata` | — | transport | gateway |
| `AuditEntry`, `SecurityEvent`, `ExecutionStatus` | — | audit impl | gateway |
| `RollbackEntry`, `RollbackStatus` | — | state impl | gateway |
| `SecurityEventType` | — | — | gateway |

---

## Credential vault facade

`executor_sdk.services.credential_vault` re-exports from `intentframe_credentials`
so packs do not import that package directly:

- `CredentialVault` (ABC)
- `KeyringVault`, `EnvVault`, `HashiCorpVault`, `ServiceVault`
- `register_credential_vault`, `create_credential_vault`

Importing the module registers all four backends as a side effect.

---

## Related docs

- [`executor/README.md`](../executor/README.md) — executor host and gateway
- [`docs/executor.md`](../docs/executor.md) — architecture overview
- [`docs/modules.md`](../docs/modules.md) — module map and credential path
- [`intentframe_native_kit/README.md`](../intentframe_native_kit/README.md) — first-party packs
