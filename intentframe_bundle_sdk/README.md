# IntentFrame Bundle SDK

Governed lifecycle contract for **action** and **domain** plugins. The substrate
(`intentframe_server`, `intentframe_components`) orchestrates the pipeline;
this package owns hook shapes, registry, loader, fixed gate order, and the data
that flows to Analysis Engine / Guardian on the UNDECIDED path.

First-party reference implementation: `intentframe_native_bundles/`.

---

## What this package is (and is not)

| Layer | Owns | Must not |
|-------|------|----------|
| **Substrate** | User policy resolution, pipeline, AE/Guardian assembly | Read constraint field names; call per-family checkers; import plugin modules |
| **Bundle SDK** (this package) | Hook contract, runner order, registry, loader, `BundleAIContext` | Import first-party evidence types or substrate checkers |
| **Plugins** | Action ids, constraints, enforcement, enrichment, AI context | See `UserPolicy` or other actions' permissions |

Plugins run **in-process** with full Python access. The SDK is production-ready
for first-party / single-tenant deployment today. Third-party plugin hosting
(versioning, sandboxing, instance-scoped registry) is tracked in
[`TODO/path_to_production.md`](TODO/path_to_production.md).

---

## Three separate concepts

Do not collapse these:

1. **Action bundles** — own action ids and action-level constraints (`ActionBundle`).
2. **Domain bundles** — own cross-cutting domain logic only (`DomainBundle`); no action ids.
3. **Domain routes** — routing metadata (`domain_id` → action ids) via `register_domain_routes()`.

---

## Package layout

```
intentframe_bundle_sdk/
  action.py       ActionBundle base class
  domain.py       DomainBundle base class
  types.py        ActionPermission, BundleContext, BundlePhaseOutcome, …
  registry.py     register_* / lookup helpers
  loader.py       ensure_loaded, validate_policy_against_registry
  runner.py       DeterministicRunner — fixed gate order
  lifecycle.py    startup_bundles, shutdown_bundles
  audit_dump.py   JSON-safe context serialization for audit logs
```

Public API is re-exported from `intentframe_bundle_sdk/__init__.py` (`__all__`).

---

## Boot

```python
from intentframe_bundle_sdk import ensure_loaded, validate_policy_against_registry

ensure_loaded(["intentframe_native_bundles"])
validate_policy_against_registry(user_policy)
```

`ensure_loaded()`:

- Imports each plugin package and calls `register_bundles(registry)`.
- Is **idempotent** for the same package set.
- Raises if called again with a **different** package set (process-wide registry).
- Requires `register_bundles(registry)` — importing a plugin package must **not** register bundles as a side effect.

`validate_policy_against_registry()` fails closed when policy references actions or
domains that cannot be enforced at runtime.

Runtime shutdown (typically from `IntentFrameRuntime.aclose()`):

```python
from intentframe_bundle_sdk import startup_bundles, shutdown_bundles

await startup_bundles()
await shutdown_bundles()  # per-bundle aclose(), timeout + ExceptionGroup on failure
```

---

## Deterministic gate order

`DeterministicRunner` is the **sole runtime caller** of bundle hooks. Authors do
not override ordering.

```
permission          (substrate — DeterministicGuardian, before runner)
  → prepare_evidence
  → enrich            (must not BLOCK or ALLOW)
  → enforce_constraints
  → domain.enforce    (per domains_for_action, in route order)
  → structural_gates
  → passive_read ALLOW (SDK-owned, from passive_read_action_ids + safe=True)
  → allow_gates
  → UNDECIDED + BundleAIContext → AE → Guardian
```

Terminal **BLOCK** / **ALLOW** results carry no `constraint_context`. Constraint
prompt text is built on the **UNDECIDED** path only.

---

## ActionBundle hooks

Subclass `ActionBundle` and set:

- `bundle_id: str`
- `action_ids: frozenset[str]`
- `passive_read_action_ids: frozenset[str]` — subset of `action_ids`; SDK-owned passive-read ALLOW

| Hook | Sync/async | When |
|------|------------|------|
| `startup()` | async | Optional; once after registration |
| `prepare_evidence()` | async | Pre-enforcement evidence (command shield, file intel, …) |
| `enrich()` | async | Resolve external metadata into `ctx.enriched_intent` |
| `validate_constraints()` | sync | Startup only — policy shape validation |
| `enforce_constraints()` | sync | Runtime constraint enforcement |
| `structural_gates()` | sync | Path/floor BLOCKs |
| `allow_gates()` | sync | Custom ALLOW fast paths |
| `build_ai_context()` | sync | AE/Guardian prompt material (UNDECIDED path) |
| `describe_constraints()` | sync | Optional human-readable constraint text for prompts |
| `aclose()` | async | Optional; release bundle-owned resources (must be idempotent) |

### Rules for action bundle authors

- Hooks receive a per-action `ActionPermission` only — **never** `UserContext` or `UserPolicy`.
- `constraints` are opaque `dict`s; parse fresh on each hook call. Do not cache parsed Pydantic models on the bundle instance.
- Async hooks are for I/O; sync hooks must be pure compute (keep them fast).
- External clients (IMAP, DB pools, …) must be **instance state**, not module globals. Open lazily; close in `aclose()`.
- `enrich()` must return `CONTINUE` only — terminal BLOCK/ALLOW from enrichment is a runner error.

Minimal skeleton:

```python
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import ActionPermission, BundleContext, BundlePhaseOutcome

class MyActionBundle(ActionBundle):
    bundle_id = "my_family"
    action_ids = frozenset({"MY_ACTION"})
    passive_read_action_ids = frozenset()

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            MyConstraints.model_validate(action_permission.constraints)

    def enforce_constraints(
        self,
        intent,
        action_permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        # …
        return BundlePhaseOutcome.continue_(ctx)
```

Reference: `intentframe_native_bundles/actions/email/bundle.py` (enrichment + `aclose`).

---

## DomainBundle hooks

Subclass `DomainBundle` and set `bundle_id`, `domain_id`.

| Hook | When |
|------|------|
| `validate()` | Startup — domain constraint shape |
| `enforce()` | Runtime — BLOCK or pass (never ALLOW) |
| `describe()` | Optional prompt text for UNDECIDED path |
| `startup()` / `aclose()` | Same lifecycle contract as action bundles |

Domain bundles do **not** declare which actions they apply to. Register routing separately:

```python
registry.register_domain_bundle(FinanceDomainBundle())
registry.register_domain_routes({
    "finance": frozenset({"PAY_INVOICE"}),
})
```

---

## Plugin package entry point

Each plugin package exposes exactly one registration function:

```python
def register_bundles(registry) -> None:
    registry.register_action_bundle(MyActionBundle())
    registry.register_domain_bundle(MyDomainBundle())
    registry.register_domain_routes(DOMAIN_ROUTES)
```

See `intentframe_native_bundles/__init__.py` for the first-party pattern.

---

## Key types

| Type | Role |
|------|------|
| `ActionPermission` | Per-action `safe` + opaque `constraints` dict |
| `BundleContext` | Mutable phase context: `intent`, `evidence`, `enriched_intent`, enrichment ledger |
| `BundlePhaseOutcome` | `CONTINUE` / `BLOCK` / `ALLOW` from a single hook |
| `BundleDeterministicResult` | Full runner result: `BLOCK` \| `ALLOW` \| `UNDECIDED` + optional `BundleAIContext` |
| `BundleAIContext` | Bundle-built AE/Guardian instructions + `ConstraintPromptContext` |
| `ConstraintPromptContext` | Runner-built constraint summary for UNDECIDED prompts |

`ctx.effective_intent` is `enriched_intent or intent` — use this downstream after enrichment.

---

## Resource lifecycle

Bundles that open external resources must:

1. Hold handles on the bundle **instance** (e.g. `self._client`).
2. Implement idempotent `async def aclose(self)`.
3. Never use module-level singletons for clients.

`shutdown_bundles()` calls every registered bundle's `aclose()` in reverse order,
with a per-bundle timeout (default 5s). Failures are aggregated into
`BaseExceptionGroup` — one bad close does not skip the rest.

**Future extension (not implemented):** bundles with many disposables may use an
`asyncio.AsyncExitStack` inside `startup()` and `await stack.aclose()` from
`aclose()`, or a host-provided `add_shutdown_hook()` helper. Add only when a
second bundle needs multi-resource teardown.

---

## Substrate integration

Typical wiring in `intentframe_server`:

```python
DeterministicGuardian(packages=["intentframe_native_bundles"])
  → ensure_loaded(packages) on init
  → permission gate
  → DeterministicRunner.run_action_bundle(...)
  → BundleDeterministicResult → AE / Guardian / Executor
```

`IntentFrameRuntime.startup()` / `aclose()` fan out to `startup_bundles()` /
`shutdown_bundles()` and close the executor (`aclose` or `close`, awaited if async).

Substrate components consume `BundleAIContext` prepared by the runner — they do
not dispatch into per-family checkers or re-read constraint schemas.

---

## Testing

| Test file | What it guards |
|-----------|----------------|
| `tests/test_bundle_sdk_invariants.py` | Hook contracts, mutation safety, gate order |
| `tests/test_bundle_loader.py` | Loader idempotency, policy validation |
| `tests/test_bundle_lifecycle.py` | `startup_bundles` / `shutdown_bundles` orchestration |
| `tests/test_deterministic_gate_matrix.py` | Parity vs legacy deterministic baseline |
| `tests/test_boundary_imports.py` | Substrate must not import plugin modules |
| `tests/native_bundles/test_email_bundle_lifecycle.py` | Instance-owned client + `aclose` |
| `tests/test_runtime_email_lifecycle_integration.py` | Full registry shutdown path |

Run SDK-focused tests:

```bash
uv run pytest tests/test_bundle_sdk_invariants.py tests/test_bundle_loader.py \
              tests/test_bundle_lifecycle.py tests/test_deterministic_gate_matrix.py -v
```

---

## Related documentation

- [docs/dev/action-family-wiring.md](../docs/dev/action-family-wiring.md) — checklist for adding action families
- [docs/_internal_/substrate-plugin-refactor.md](../docs/_internal_/substrate-plugin-refactor.md) — refactor narrative and outcomes
- [docs/modules.md](../docs/modules.md) — workspace module map
- [`TODO/path_to_production.md`](TODO/path_to_production.md) — gaps before third-party plugin platform
