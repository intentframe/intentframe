Honest answer: **production-ready for first-party use, not yet for third-party plugins.**

## What Is Production-Ready

**Hot path (intent processing)**
- `DeterministicRunner` gate order is fixed and enforced; no plugin-overridable ordering.
- `ActionPermission` is deep-copied per call; mutation-safety is tested.
- `BundleAIContext` flows cleanly to AE/Guardian; substrate doesn’t reach into plugin internals.
- `enforce_constraints` returning `NotImplementedError` correctly fails-closed (`no_enforcement` BLOCK).
- Parity preserved against the legacy `66e567c` deterministic gate matrix and prompt baselines.

**Boot path**
- `ensure_loaded()` is idempotent and rejects conflicting package sets.
- `validate_policy_against_registry()` fails closed on unknown actions/domains and shape mismatches.
- `register_domain_routes()` validates domain ids and rejects orphan references.

**Resource lifecycle**
- `startup()` / `aclose()` contract with timeout + `BaseExceptionGroup` aggregation.
- Email bundle proves the pattern; integration test covers the full registry path.
- Substrate no longer imports plugin modules for cleanup (boundary test enforces this).

**Tests**
- ~85 lifecycle/boundary/parity tests passing.
- Boundary AST scan, leak smoke, idempotency parametrized over every registered bundle.

## What Is Not Production-Ready

**1. Process-wide singletons in the registry**
`_ACTION_BY_ID`, `_ACTION_INSTANCES`, `_DOMAIN_BY_ID`, `_ACTION_TO_DOMAINS`, `_LOADED_PACKAGES` are module globals.
- One process = one bundle set. No multi-tenant isolation.
- `ensure_loaded` enforces a single package set per process — fine for `intentframe-core`, hostile for embedding the SDK in a host that wants different bundle sets per request/tenant.
- Test suite needed `_bundle_registry_snapshot.py` precisely because the global state is fragile.

**2. Trust model assumes first-party plugins**
- Bundle code runs **in-process** with full Python access. No sandbox, no capability restriction, no resource quotas.
- A misbehaving bundle can corrupt `BundleContext`, hang `aclose`, or import anything in `sys.path`.
- The refactor doc explicitly flags MCP/WASM/Cedar as future partner-extension surfaces — none implemented.

**3. Versioning and stability**
- No `bundle_sdk_version` or `min_sdk_version` declared on bundles.
- Adding a new gate phase to `DeterministicRunner` would silently break out-of-tree bundles.
- Breaking-change policy is implicit (bundles live in-tree).

**4. Observability**
- `audit_dump` exists for tests; no production telemetry hooks (per-hook latency, BLOCK/ALLOW counters by `bundle_id`, `aclose` failures by bundle).
- `shutdown_bundles` logs failures but doesn’t emit metrics.
- No structured trace from `process_intent` → bundle hooks.

**5. Concurrency model is unspecified**
- `DeterministicRunner.run_action_bundle` is async, but bundles can do CPU-heavy work in sync hooks (`enforce_constraints`, `structural_gates`, `build_ai_context`) that block the event loop.
- No documented contract for "sync hooks must be O(small)."
- No timeout on hook execution beyond `aclose`.

**6. Hot reload / dynamic policy**
- Loader prevents reloading; `validate_policy_against_registry` runs once at boot.
- Changing policy at runtime requires process restart.
- The doc note "do not cache parsed constraints" implies hot reload was a goal, but the loader contradicts it.

**7. Domain routing is global**
- `register_domain_routes` mutates `_ACTION_TO_DOMAINS` once. Per-tenant or A/B routing variants are not supported.

**8. Missing operational features**
- No `quiesce()` (drain-then-close) — `aclose` is hard close.
- No health check per bundle (`browser` driver crash, `EmailClient` IMAP login broken).
- No structured `BundleError` hierarchy — bundles raise arbitrary exceptions, runner relies on `Exception` catch in DG.
- No async executor `aclose` is supported (added recently), but the executor base class doesn’t require it — accidental sync-`close` regressions won’t be caught.

**9. Documentation gaps**
- No "writing a bundle" tutorial for external authors.
- No semver/compatibility statement.
- No published API surface (`__all__` exists; stability tier doesn’t).

## Production Readiness By Use Case

| Use case | Ready? | Notes |
|----------|--------|-------|
| First-party `intentframe-core` deployment | **Yes** | Boundary, parity, lifecycle, leak smoke all green |
| Single-tenant SaaS with first-party bundles only | **Yes** | Same as above |
| Multi-tenant runtime with shared bundle set | Partial | Globals make policy/domain isolation per tenant impossible |
| Multi-tenant with different bundle sets per tenant | **No** | Process-wide registry; would need rearchitect |
| Third-party / partner plugins | **No** | No sandbox, no version pinning, no capability boundary |
| Hot policy reload | **No** | Loader is single-shot |

## What I'd Want Before Calling It "Plugin Platform" Production-Ready

In rough priority:

1. Make the registry **instance-scoped** (`Registry()` object) instead of module globals; keep a process-level default for backward compat.
2. Declare `BUNDLE_SDK_VERSION` and require bundles to declare `min_sdk_version`.
3. Add per-hook timeouts (default 1s sync, 5s async) with structured `BundleHookTimeout`.
4. Add a `BundleError` hierarchy (`BundleConfigError`, `BundleRuntimeError`, `BundleHookTimeout`).
5. Emit OTel/metrics from `DeterministicRunner` per bundle/hook.
6. Define and document a sync-hook compute budget; lint/test that hooks don't sleep.
7. Document the boundary contract in a public `intentframe_bundle_sdk/CONTRACT.md`.

## Bottom Line

**For your current production deployment** (first-party bundles, single process), it's solid: contract is enforced, lifecycle leaks are sealed, parity holds. Ship it.

**As a public B2B plugin platform** (the original goal in `substrate-plugin-refactor.md`), it's about 60% there. The hot-path correctness is excellent; the platform-grade stuff (versioning, sandboxing, observability, instance-scoped registry) is not built yet — and most of it is intentionally deferred to the partner-extension future (`docs/_internal_/action-wiring-refactor.md`).