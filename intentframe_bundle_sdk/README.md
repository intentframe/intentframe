# IntentFrame Bundle SDK

Governed lifecycle contract for **action** and **domain** plugins. The substrate
(`intentframe_server`, `intentframe_components`) orchestrates the pipeline;
this package owns hook shapes, registry, loader, fixed gate order, and the data
that flows to Analysis Engine / Guardian on the UNDECIDED path.

First-party reference implementation: `intentframe_native_kit/intentframe_native_bundles/`.

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
  action.py              ActionBundle base class (includes onboarding_guardrails hook)
  domain.py              DomainBundle base class
  types.py               ActionPermission, BundleContext, BundlePhaseOutcome, …
  registry.py            register_* / lookup helpers (incl. register_onboarding_manifest)
  loader.py              ensure_loaded, validate_policy_against_registry
  runner.py              DeterministicRunner — fixed gate order
  lifecycle.py           startup_bundles, shutdown_bundles
  trace.py               Internal lifecycle audit log (bundle-sdk.log)
  audit_dump.py          JSON-safe context serialization for audit logs
  onboarding.py          render_onboarding_bundle_context — middle-section assembly
  onboarding_manifest.py OnboardingManifest — cross-bundle onboarding sections
```

Public API is re-exported from `intentframe_bundle_sdk/__init__.py` (`__all__`).

---

## Boot

```python
from intentframe_bundle_sdk import ensure_loaded, validate_policy_against_registry

ensure_loaded(["intentframe_native_kit.intentframe_native_bundles"])
validate_policy_against_registry(user_policy)
```

`ensure_loaded()`:

- Imports each plugin package and calls `register_bundles(registry)`.
- Is **idempotent** for the same package set.
- Raises if called again with a **different** package set (process-wide registry).
- Requires `register_bundles(registry)` — importing a plugin package must **not** register bundles as a side effect.

`validate_policy_against_registry()` fails closed when policy references actions or
domains that cannot be enforced at runtime. Each `validate_constraints` and
`DomainBundle.validate` call is recorded in the internal trace log (see
[Lifecycle trace](#lifecycle-trace-internal-audit)).

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
| `onboarding_guardrails()` | sync | Paste-ready markdown for the onboarding system-prompt middle section (default: `""`) |
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

Reference: `intentframe_native_kit/intentframe_native_bundles/actions/email/bundle.py` (enrichment + `aclose`).

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

## Onboarding

`onboarding_guardrails()` on each `ActionBundle` returns a paste-ready markdown string that the onboarding engine inserts into its meta-LLM system prompt. Bundles that have no onboarding copy return `""` (the default).

Cross-bundle sections (rules that apply regardless of which bundles are active) are registered via `OnboardingManifest`:

```python
from intentframe_bundle_sdk import OnboardingManifest, register_onboarding_manifest

manifest = OnboardingManifest(
    sections=(
        "### My Cross-Cutting Rule\n- ...",
    ),
)
registry.register_onboarding_manifest(manifest)
```

`render_onboarding_bundle_context(allowed_action_ids)` assembles the middle section:

1. Iterates registered action bundles; includes `onboarding_guardrails()` for bundles whose `action_ids` intersect `allowed_action_ids`.
2. Appends all `OnboardingManifest.sections` unconditionally.

The top and bottom of the system prompt are owned by `intentframe_components/onboarding/instructions.py`; the SDK only provides the middle.

---

## Plugin package entry point

Each plugin package exposes exactly one registration function:

```python
def register_bundles(registry) -> None:
    registry.register_action_bundle(MyActionBundle())
    registry.register_domain_bundle(MyDomainBundle())
    registry.register_domain_routes(DOMAIN_ROUTES)
    registry.register_onboarding_manifest(MY_ONBOARDING_MANIFEST)  # optional
```

See `intentframe_native_kit/intentframe_native_bundles/__init__.py` for the first-party pattern.

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
core_config = load_core_config()  # INTENTFRAME_CORE_CONFIG -> core.yaml
DeterministicGuardian(packages=core_config.bundles)
  → ensure_loaded(packages) on init
  → permission gate
  → DeterministicRunner.run_action_bundle(...)
  → BundleDeterministicResult → AE / Guardian / Executor
```

Each bundle ref is either a short name advertised under the
`intentframe.bundles` entry-point group or a dotted module path exposing
`register_bundles(registry)`.

`IntentFrameRuntime.startup()` / `aclose()` fan out to `startup_bundles()` /
`shutdown_bundles()` and close the executor (`aclose` or `close`, awaited if async).

Substrate components consume `BundleAIContext` prepared by the runner — they do
not dispatch into per-family checkers or re-read constraint schemas.

---

## Lifecycle trace (internal audit)

The SDK maintains its **own** forensic log, separate from substrate audit entries
and from `BundleDeterministicResult`. Callers of the runner never receive trace
data on the wire; an auditor reads the bundle-runtime process log directly.

**Log file:** `~/.intentframe/logs/bundle-sdk.log` (or `$INTENTFRAME_LOG_DIR` /
`configure_trace_logging(log_dir)` when redirected, e.g. in tests).

Each hook invocation (or deliberate skip) emits one minified JSON line via the
`bundle_sdk.trace` logger. Records capture the **full function frame** — every
positional and keyword argument bound by name through `inspect.signature`, plus
the audit-dumped return value. No curated field lists; new hook parameters show
up automatically.

Example record:

```json
{"ts": "2026-05-26T08:30:00Z", "lane": "runtime", "trace_id": "jarvis:abc123:7:email",
 "phase": "enrich", "skipped": false, "skipped_reason": null, "elapsed_ms": 1.234,
 "inputs": {"intent": {...}, "action_permission": {...}, "ctx": {...}, "verbose": false},
 "output": {"decision": "CONTINUE", "context": {...}, ...}, "raised": null, "terminal": false}
```

| Field | Meaning |
|-------|---------|
| `lane` | Which lifecycle lane (see below) |
| `trace_id` | Correlates related records (per-intent, per-boot action, per-bundle lifecycle, …) |
| `phase` | Hook name or synthetic phase (e.g. `domain_enforce:finance`, `domain_describe:finance`) |
| `skipped` | `true` when the runner chose not to call the hook |
| `inputs` / `output` | Full audit-dumped args and return value |
| `raised` | `repr(exc)` when the hook raised |
| `terminal` | `true` when the hook produced the final BLOCK/ALLOW that stopped the runner |

### Lanes

| Lane | When | Hooks traced |
|------|------|--------------|
| `boot` | Policy seed load | `ActionBundle.validate_constraints`, `DomainBundle.validate` |
| `lifecycle` | Server start / shutdown | `startup`, `aclose` on every registered bundle |
| `handshake` | Onboarding prompt assembly | `onboarding_guardrails` |
| `runtime` | Per intent in `DeterministicRunner` | All runner hooks below, plus skips for omitted phases |

Runtime lane covers: `prepare_evidence`, `enrich`, `enforce_constraints` (or skip
when no constraints), `domain_enforce:{id}`, `structural_gates`,
`_try_passive_read_allow`, `allow_gates`, `describe_constraints`,
`domain_describe:{id}`, `build_ai_context`.

Implementation lives in `trace.py` (`traced_call`, `traced_acall`, `emit_skip`).
Only SDK-internal modules call these helpers. The public surface for integrators
is `configure_trace_logging()` — re-exported from `intentframe_bundle_sdk` to
point the log at a custom directory. Trace helpers are not part of the stable
plugin author API.

When bundle-runtime becomes a separate UDS process (see
`policy_registry/TODO/bundle_validator.md`), this log moves with that process;
`BundleDeterministicResult` stays unchanged.

Full querying guide: [docs/tracing_guide.md](docs/tracing_guide.md).

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
| `tests/test_bundle_sdk_trace.py` | Trace log format, terminal markers, boot/runtime hook coverage |
| `tests/test_onboarding_sdk.py` | `render_onboarding_bundle_context`, manifest sections |
| `tests/test_onboarding_constraint_summary.py` | Meta-prompt contract, `_summarize_intent_limits` |

Run SDK-focused tests:

```bash
uv run pytest tests/test_bundle_sdk_invariants.py tests/test_bundle_loader.py \
              tests/test_bundle_lifecycle.py tests/test_bundle_sdk_trace.py \
              tests/test_deterministic_gate_matrix.py -v
```

---

## Related documentation

- [docs/tracing_guide.md](docs/tracing_guide.md) — read and query `bundle-sdk.log` (pretty JSON, per-intent traces, test runs)
- [docs/dev/action-family-wiring.md](../docs/dev/action-family-wiring.md) — checklist for adding action families
- [docs/_internal_/substrate-plugin-refactor.md](../docs/_internal_/substrate-plugin-refactor.md) — refactor narrative and outcomes
- [docs/modules.md](../docs/modules.md) — workspace module map
- [`TODO/path_to_production.md`](TODO/path_to_production.md) — gaps before third-party plugin platform
