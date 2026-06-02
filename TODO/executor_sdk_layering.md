# Executor SDK layering — current acceptance and future split

Status: **accepted for now** · Target: post–third-party / hardening phase

Related: [`executor_sdk/README.md`](../executor_sdk/README.md)

---

## Current state (fine today)

`executor_sdk` currently mixes three concerns in one package:

| Concern | Examples today | Who imports |
|---------|----------------|-------------|
| **Adapter author contract** | `CapabilityAdapter`, `register_adapter`, `AdapterManifest`, `ExecutionResult` | Adapter packs |
| **Platform author contract** | `TransportServer`, `AuthVerifier`, `AuditLogger`, `StateStore`, `register_*` | Platform packs (e.g. posix) |
| **Executor host wiring** | `create_*` factories, `CredentialScrubber`, `HashChain`, dispatch/gateway exceptions, config constants | `executor/` only |

That overlap is **acceptable for the current trust model**:

- Executor packs are expected to be **first-party or org-trusted** code (same repo, same deploy boundary).
- Packs run **in-process**; `register_*` is wiring, not isolation.
- Most third-party work is **adapters only**; platform base (posix) is provided by IntentFrame or the org.
- Moving symbols now adds churn without a concrete untrusted-pack requirement.

Document the intended boundaries in README; do not block shipping on a three-package split.

---

## Why split later

When any of these become true, the monolithic `executor_sdk` becomes misleading:

- Untrusted or marketplace executor packs (out-of-tree, versioned, multi-tenant).
- Adapter-only packs must not *see* transport/auth/storage extension points in the same namespace.
- CI / docs need a hard guarantee that adapter authors import a minimal surface.
- Executor host code should not share a package name with “plugin author SDK.”

Goals of the future layout:

1. **Adapter authors** import a small, stable adapter SDK.
2. **Platform authors** import platform/backend contracts (or inherit from org-provided base pack).
3. **Executor host** owns registries, factories, gateway helpers, and config defaults.
4. **Shared wire types** live in a neutral package both host and SDKs import (no `executor/` ↔ pack circular deps).

---

## Proposed target layout (not implemented)

```text
intentframe_executor_contracts/     # or intentframe_executor_core
  models.py                         ExecutionRequest, ExecutionResult, AuditEntry, …
  exceptions.py                     shared error types used at boundaries
  constants.py                      wire-safe defaults (adapter timeout, transport paths)

executor_sdk/                       # adapter + platform author surface (trimmed)
  adapters/                         CapabilityAdapter, register_adapter
  platform/                         TransportServer, AuthVerifier, AuditLogger, …
                                    register_* only (no create_*)
  services/virtual_filesystem.py    VFS helpers for file adapters / platform VFS

executor/                           # host (unchanged role, richer imports)
  registries.py                     _ADAPTER_REGISTRY, _AUTH_REGISTRY, …
  factories.py                      create_adapter, create_transport, …
  services/
    credential_scrubber.py
    hash_chain.py                   gateway append path; optional verify helpers for storage
```

Alternative naming if “contracts” feels too close to `intentframe_core`:

- `intentframe_executor_types` — DTOs only
- `executor_sdk` — author-facing registration + ABCs
- `executor` — runtime host

Pick one neutral package name and keep it parallel to `intentframe_core` + `intentframe_bundle_sdk`.

---

## What moves out of `executor_sdk` (host-only)

Move under `executor/` (or `executor/internal/`), not author SDK:

- `create_adapter`, `create_transport`, `create_auth_verifier`
- `create_audit_logger`, `create_state_store`, `create_credential_vault`
- Module-level registry dicts (`_ADAPTER_REGISTRY`, …) — owned by executor; packs receive a registry handle or call scoped `register_*` on a host-provided object
- `CredentialScrubber` (gateway pipeline)
- `HashChain` mutable gateway instance (keep narrow verify/hash helpers on platform side if needed)
- `AdapterNotFoundError`, `RequestValidationError` (dispatch/gateway)
- Config/schema constants: `DEFAULT_MAX_WORKERS`, `DEFAULT_CONFIG_FILENAME`, table names, scrubber re-exports

---

## What stays in author SDK

**Adapter tier**

- `CapabilityAdapter`, `register_adapter`
- `AdapterManifest`, `ExecutionResult`
- VFS: `MountPointConfig`, `expand_path`, `VirtualFileSystemError`

**Platform tier** (separate subpackage or optional import path)

- `TransportServer`, `AuthVerifier`, `AuditLogger`, `StateStore`, `VirtualFileSystem`, `CredentialVault`
- Matching `register_*` functions
- Wire models needed to implement those ABCs (`AuthorizationProof`, `AuditEntry`, …)

**Shared via contracts package**

- All pydantic wire models and enums crossing host ↔ pack boundaries
- Base `ExecutorError` hierarchy used in public contracts

---

## Registration hardening (optional, same milestone)

Today: global `register_*()` mutates module-level dicts.

Later options (pick one):

1. **Host-passed registry** — `def register_all(registry: PackRegistry) -> None` with `AdapterRegistryView` vs full `PlatformRegistry`.
2. **Entry-point metadata** — pack declares role (`adapter` | `platform`) in pyproject; loader rejects platform registrations from adapter-only packs.
3. **Out-of-process adapters** — only real untrusted boundary; in-process registry views are ergonomics, not security.

---

## Migration checklist (when started)

- [ ] Add `intentframe_executor_contracts` (or chosen name); move `models.py` + shared exceptions/constants.
- [ ] Point `executor/` and `executor_sdk/` at contracts package; no pack imports contracts via `executor_sdk.models` long-term (re-export shim during transition).
- [ ] Move `create_*` + registry dicts into `executor/registries.py` + `executor/factories.py`.
- [ ] Move `CredentialScrubber`, gateway `HashChain` usage into `executor/services/`.
- [ ] Split `executor_sdk` public API: `executor_sdk.adapters` vs `executor_sdk.platform` (or two install extras).
- [ ] Update native kit imports; add boundary test (adapter pack must not import platform/executor modules).
- [ ] Update [`executor_sdk/README.md`](../executor_sdk/README.md) and [`docs/modules.md`](../docs/modules.md).
- [ ] Deprecation shims in `executor_sdk` for one release if external packs exist.

---

## Non-goals (this TODO)

- Sandboxing untrusted pack Python in-process
- Hot-reloading packs at runtime
- Replacing posix as the documented minimum platform base

Those belong in separate production-hardening tracks (see [`intentframe_bundle_sdk/TODO/path_to_production.md`](../intentframe_bundle_sdk/TODO/path_to_production.md) for the bundle-side analogue).
