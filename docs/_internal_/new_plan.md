Here is the consolidated plan, with v5 winning wherever v4 and v5 disagree. No PR labels — only sequential implementation phases.

**Last updated:** 2026-05-24 — aligned with pass 12 SDK routing restoration on `refactor-substrate`.

---

# Bundle SDK Plugin Refactor — Combined Plan (final)

## 0. Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1 — SDK foundations | **Done** | `ActionPermission`, `BundlePhaseOutcome`, strict registry, hook surface |
| 2 — Policy registry opaque dicts | **Done** | `constraints` and `domain_constraints` are raw dicts in `policy_registry/models.py` |
| 3 — Plugin family migration | **Done** | `actions/<family>/` + `domains/{finance,deletion}/`; plugin-local constraints; `PAY_INVOICE` on `ApiActionBundle` |
| 4 — Runner wiring | **Done** | Passive-read gate, constraint prompt context, **SDK domain routing** (see §0.1) |
| 5 — Substrate cleanup | **Done** | Guardian reads `bundle_ai_context.constraint_context` only; no runtime checker imports |
| 6 — Legacy scaffolding deletion | **Done** | `guardian/checkers/`, duplicate top-level family folders, `policy_registry/constraints/`, `policy_registry/domains/` removed; `tests/_bundle_loader.py` added |
| 7 — Loader and startup validation | **Done** | `loader.py`, `ensure_loaded`, DG `packages=` wiring, shim removed |
| 8 — Tests rewrite and verification | **Done** | `test_bundle_loader.py`, `test_bundle_sdk_invariants.py`, existing routing/order tests |
| 9 — Documentation | **Done** | SDK docstrings, `docs/dev/action-family-wiring.md`, `docs/modules.md` updated |

Test suite (last run on branch): **1431 passed**, 9 xfailed (non-sandbox).

### 0.1 Pass 12 SDK routing — restored

Three things stay separate; do not collapse them:

1. **Action bundles** (`actions/<family>/`) — own action ids and action-level constraints.
2. **Domain bundles** (`domains/<finance|deletion>/`) — own domain logic only; no action ids.
3. **Domain routes** (`domain_routes.py`) — routing manifest; registered via `register_domain_routes()`.

Runtime routing authority is **plugin-owned SDK registry**, not `action_registry.ACTION_DOMAINS`:

- `register_domain_routes(DOMAIN_ROUTES)` merges routes after domain bundles register.
- `domains_for_action(action_id) -> tuple[str, ...]` — supports many-to-many.
- `_ROUTED_DOMAIN_IDS` + route-aware `validate_policy_domain_constraints()` — fail closed if bundle missing or no route.
- `registered_domain_ids()`, `routed_domain_ids()` for introspection.
- Runner loops `for domain_id in domains_for_action(action_id)`; **does not import `action_registry`**.

`ACTION_DOMAINS` in `action_registry/types.py` remains for actor, demo, and docs only — not the deterministic runner path.

### 0.2 Intentional drifts from pass 12 (`5719a35`)

| Item | Pass 12 | Current (kept) |
|------|---------|----------------|
| Domain hooks | `validate_constraints`, `check_domain`, `summarize_constraints` | `validate`, `enforce`, `describe` |
| Domain return type | `tuple[bool, str]` | `BundlePhaseOutcome` |
| Domain identity | `domain_id` only | `domain_id` + `bundle_id` |
| Constraint schemas | `policy_registry.domains.*` | `domains/*/constraints.py` (plugin-local) |
| Finance action family | `FinanceActionBundle` existed | Removed — `PAY_INVOICE` on `ApiActionBundle` only |

## 1. Goal

Make IntentFrame a strict plugin platform.

- The substrate (`intentframe_components/`, `intentframe_server/`) orchestrates and consumes data; it never reads constraint field names, never re-runs enforcement, never calls bundle methods at prompt-build time.
- The SDK (`intentframe_bundle_sdk/`) owns the lifecycle contract, runner, registry, loader, and the data shapes that flow from bundles to the AI layer.
- Plugins (`intentframe_native_bundles/<family>/`) own action ids, constraint schemas, evidence, validation, enforcement, descriptions, structural and allow gates, and AI context.
- The `policy_registry` stores opaque dict constraints only — no Pydantic constraint unions, no domain constraint typed union.

## 2. Boundary Rules (Hard)

| Layer | Owns | Must Not |
|-------|------|----------|
| Substrate / runtime | UserPolicy resolution, permission gate, fixed gate order, AI engines, audit, executor wiring | Read `action_permission.constraints` field names; re-run enforcement; call bundle/domain hooks at prompt-build time; import plugin schemas |
| Bundle SDK | Lifecycle contract, `BundleContext`, `BundleAIContext`, `ConstraintPromptContext`, `DeterministicRunner`, registry, loader, base `ActionBundle` and `DomainBundle` | Import first-party evidence types, substrate checkers, or `policy_registry.constraints.*` |
| Plugins | Action ids, constraint schema, `validate_constraints`, `enforce_constraints`, `describe_constraints`, evidence, structural gates, allow gates, AI context | See `UserContext`, `UserPolicy`, or any other family's policy slice |

Three additional invariants:

- The runner is the only runtime caller of bundle hooks.
- `intentframe_components/*` consumes prepared prompt data from `BundleAIContext`; it never calls `action_bundle_for`, `domain_bundle_for`, `describe_constraints`, `domain_bundle.describe`, `CONSTRAINT_CHECKERS`, or any summarize helper.
- Bundles receive a deep-copied per-action `ActionPermission` (`safe` + opaque `constraints` dict); they never see `UserContext`, `UserPolicy`, or another action's permission.

## 3. Final Hook Surface

```python
class ActionBundle(ABC):
    bundle_id: str
    action_ids: frozenset[str]
    passive_read_action_ids: frozenset[str] = frozenset()

    async def prepare_evidence(self, intent, ctx, *, verbose=False) -> BundlePhaseOutcome: ...
    async def enrich(self, intent, ctx, *, verbose=False) -> BundlePhaseOutcome: ...
    def validate_constraints(self, action_permission) -> None: ...
    def enforce_constraints(self, intent, action_permission, ctx, *, verbose=False) -> BundlePhaseOutcome: ...
    def structural_gates(self, intent, ctx) -> BundlePhaseOutcome: ...
    def allow_gates(self, intent, action_permission, ctx) -> BundlePhaseOutcome: ...
    def build_ai_context(self, intent, action_permission, ctx) -> BundleAIContext: ...
    def describe_constraints(self, action_permission) -> str | None: ...

class DomainBundle(ABC):
    bundle_id: str
    domain_id: str

    def validate(self, domain_constraints: dict[str, Any] | None) -> None: ...
    def enforce(self, intent, domain_constraints: dict[str, Any] | None) -> BundlePhaseOutcome: ...
    def describe(self, domain_constraints: dict[str, Any] | None) -> str | None: ...
```

Hook semantics:

- `validate_constraints` and `validate` are startup-only; required when seeded constraints exist; raise on bad shape; never called at intent time.
- `enforce_constraints` is required when constraints exist; default raises `NotImplementedError` → runner converts to BLOCK with `matched_gate="no_enforcement"`.
- `describe_constraints` and `describe` are optional; only the runner calls them, and only for `UNDECIDED` paths.
- `passive_read_action_ids` must be a subset of `action_ids`; registry raises on violation.
- `prepare_evidence`, `enrich`, `structural_gates` do not see policy.

## 4. Final Gate Order

```
permission gate
  prepare_evidence
  enrich
  enforce_constraints                      (only if action_permission.constraints is not None)
  domain enforce                            (for each domain_id in domains_for_action(action_id))
  structural_gates
  SDK passive-read ALLOW                    (action ∈ bundle.passive_read_action_ids AND action_permission.safe)
  allow_gates                               (custom plugin ALLOW fast paths; e.g. terminal read-only)
  build_ai_context + ConstraintPromptContext  (runner-built, only on UNDECIDED)
  UNDECIDED → AI (AE then Guardian)
```

Rules:

- All BLOCK gates run before any deterministic ALLOW.
- SDK passive-read ALLOW runs before plugin `allow_gates` to preserve legacy ordering (passive-read first, terminal read-only second).
- Constraint descriptions are built only on the path to AI; terminal deterministic ALLOW/BLOCK do not produce prompt context.

## 5. SDK Data Shapes

```python
@dataclass
class ActionPermission:                    # SDK-side concrete dataclass
    safe: bool
    constraints: dict[str, Any] | None
    def copy_with_constraints(self, constraints): ...

class BundleContext:                       # mutable lifecycle ctx; evidence: dict; no constraint_checker_skipped
    intent: IntentFrame
    enriched_intent: IntentFrame | None
    evidence: dict[str, Any]

@dataclass
class ConstraintPromptContext:
    action_constraints: str = "No specific constraints"
    domain_constraints: list[str] = field(default_factory=list)
    enforced_domains: list[str] = field(default_factory=list)

@dataclass
class BundleAIContext:
    ae_system_instructions: str | None
    ae_external_context: str | None
    ae_prompt_label: str | None
    constraint_context: ConstraintPromptContext | None = None

@dataclass
class BundlePhaseOutcome:
    decision: PhaseDecision
    context: BundleContext
    reason: str | None
    matched_gate: str | None
    def to_deterministic_result(self) -> BundleDeterministicResult: ...
```

`BundlePhaseOutcome.to_deterministic_result()` sets `decision_path = self.matched_gate if self.matched_gate else "deterministic"`. The SDK never hardcodes any named gate string; bundles signal them via `matched_gate` (e.g. `"command_shield"`, `"passive_read"`).

## 6. DeterministicRunner Pseudo-Code

```python
ctx = BundleContext(intent=intent.model_copy(deep=True))

ev = await bundle.prepare_evidence(intent, ctx)
if ev.terminal: return ev.to_deterministic_result()
ctx = ev.context

en = await bundle.enrich(intent, ctx)
if en.terminal:
    raise RuntimeError("enrich must not BLOCK/ALLOW")
record_enrichment(ctx, bundle_id=bundle.bundle_id)

if action_permission.constraints is not None:
    frozen = action_permission.copy_with_constraints(deepcopy(action_permission.constraints))
    try:
        pol = bundle.enforce_constraints(intent, frozen, ctx)
    except NotImplementedError:
        return _block("No enforce_constraints for constrained action", matched_gate="no_enforcement")
    if pol.terminal: return pol.to_deterministic_result()

domain_ids = domains_for_action(intent.action.value)
for domain_id in domain_ids:
    domain_bundle = domain_bundle_for(domain_id)
    if domain_bundle is None:
        continue
    slice_ = deepcopy(user_context.domain_constraints.get(domain_id))
    dr = domain_bundle.enforce(intent, slice_)
    if dr.terminal: return dr.to_deterministic_result()

st = bundle.structural_gates(intent, ctx)
if st.terminal: return st.to_deterministic_result()

# SDK-owned passive-read ALLOW
if intent.action.value in bundle.passive_read_action_ids and action_permission.safe:
    return _allow(matched_gate="passive_read",
                  reason=f"Permitted (deterministic: passive read): {intent.action.value}")

al = bundle.allow_gates(intent, action_permission, ctx)
if al.terminal: return al.to_deterministic_result()

# UNDECIDED path only — build prompt-ready constraint text
constraint_ctx = build_constraint_prompt_context(
    bundle, action_permission, domain_ids, user_context,
)
ai_ctx = bundle.build_ai_context(intent, action_permission, ctx)
ai_ctx = replace(ai_ctx, constraint_context=constraint_ctx)
return _undecided(ctx, ai_context=ai_ctx)
```

Constraint prompt context fallbacks (all inside the SDK runner, never in Guardian):

- `constraints is None` → `action_constraints = "No specific constraints"`
- `bundle.describe_constraints(permission)` returns `None` → `action_constraints = str(action_permission.constraints)`
- For each `domain_id` in `domains_for_action(action_id)`, `domain_bundle.describe(slice)` returns `None` → `f"{domain_id}: {slice}"`
- `enforced_domains` lists all routed domain ids for the action (from `domains_for_action`).

## 7. Fail-Closed Rules

- Allowed action with no registered bundle → BLOCK `matched_gate="no_bundle"`.
- Action with constraints but bundle does not override `enforce_constraints` → BLOCK at runtime (`matched_gate="no_enforcement"`) and fail at startup (loader's `validate_constraints` raises).
- `validate_constraints` raises at startup → loader raises → substrate refuses to start.
- Duplicate `action_id` across registered bundles → `ValueError` at registration.
- Duplicate `domain_id` across registered domain bundles → `ValueError`.
- Domain route references unregistered `domain_id` → `ValueError` at `register_domain_routes`.
- Policy declares `domain_constraints[domain_id]` but no registered bundle or no route → startup validation raises.
- Empty `bundle_id` or empty `action_ids` → `ValueError`.
- `passive_read_action_ids - action_ids` non-empty → `ValueError`.
- Unexpected exception in any bundle hook → BLOCK `matched_gate="exception"` (existing DG behavior).
- `describe_constraints` returning `None` is not fail-closed — runner applies fallback inside the SDK; never blocks.

## 8. Final Plugin Layout

```
intentframe_native_bundles/
  __init__.py                # register_bundles(registry) + temporary _ensure_first_party_bundles_loaded() shim
  actions/
    api/                     PAY_INVOICE, HTTP_GET, HTTP_POST, HTTP_PUT, HTTP_DELETE (+ ApiConstraints)
    terminal/                RUN_COMMAND
    files/                   READ_FILE, LIST_DIRECTORY, WRITE_FILE, APPEND_ROW, DELETE_FILE
    host_files/              READ_HOST_FILE, LIST_HOST_DIRECTORY, WRITE_HOST_FILE, DELETE_HOST_FILE
    email/                   all email actions
    browser/                 OPEN_URL, SEARCH_WEB, GET_PAGE_CONTENT
    message/                 SEND_MESSAGE, READ_MESSAGES
    calendar/                CREATE_EVENT, LIST_EVENTS, ...
    reminders/               reminder actions
    notes/                   note actions
    contacts/                contact actions
    clipboard/               GET_CLIPBOARD, SET_CLIPBOARD
    spotlight/               SEARCH_SPOTLIGHT
    system/                  system get/set/toggle actions
    user_io/                 user I/O actions
  domains/
    finance/                 FinanceDomainBundle only — no action ids
    deletion/                DeletionDomainBundle only — no action ids
  domain_routes.py           manifest: domain_id → action ids (registered via register_domain_routes)
```

**Routing:** `DOMAIN_ROUTES` maps domains to actions. The runner resolves domains via `domains_for_action()`, not `ACTION_DOMAINS`. First-party routes today are still 1:1 (finance → `PAY_INVOICE`; deletion → `DELETE_*`), but the registry supports many-to-many.

Per family:

- `actions.py` owns its action-id sets.
- `constraints.py` owns plugin-local Pydantic constraint parsing (only if the family has constraints).
- `bundle.py` owns action ids, passive-read ids, `validate_constraints`, `enforce_constraints`, `describe_constraints`, `structural_gates`, `allow_gates`, `build_ai_context`.
- `evidence.py` exists only where the family has typed evidence (`terminal` → `CommandIntel`, `files`/`host_files` → `FileIntel`).

Per-family passive-read ids (locked):

- `terminal`: none.
- `files`: READ_FILE, LIST_DIRECTORY.
- `host_files`: READ_HOST_FILE, LIST_HOST_DIRECTORY.
- `email`: READ_EMAIL, SEARCH_EMAIL, GET_EMAIL, DOWNLOAD_ATTACHMENT.
- `api`: HTTP_GET.
- `browser`: GET_PAGE_CONTENT (matches pass 10).
- `message`: READ_MESSAGES.
- `calendar`: LIST_EVENTS, LIST_CALENDARS, SEARCH_EVENTS.
- `reminders`: LIST_REMINDERS, LIST_REMINDER_LISTS.
- `notes`: LIST_NOTES, READ_NOTE.
- `contacts`: SEARCH_CONTACTS, GET_CONTACT.
- `clipboard`: GET_CLIPBOARD.
- `spotlight`: SEARCH_SPOTLIGHT.
- `system`: GET_SYSTEM_INFO, GET_BRIGHTNESS, GET_VOLUME, GET_MUTE, GET_DARK_MODE.

`intentframe_native_bundles/__init__.py` body:

```python
def register_bundles(registry) -> None:
    """First-party register entry point. Called by ensure_loaded() in Phase 7;
    called by _ensure_first_party_bundles_loaded() shim until then."""
    from .actions.api.bundle import ApiActionBundle
    from .actions.terminal.bundle import TerminalActionBundle
    from .actions.files.bundle import FilesActionBundle
    from .actions.host_files.bundle import HostFilesActionBundle
    from .actions.email.bundle import EmailActionBundle
    from .actions.browser.bundle import BrowserActionBundle
    from .actions.message.bundle import MessageActionBundle
    from .actions.calendar.bundle import CalendarActionBundle
    from .actions.reminders.bundle import RemindersActionBundle
    from .actions.notes.bundle import NotesActionBundle
    from .actions.contacts.bundle import ContactsActionBundle
    from .actions.clipboard.bundle import ClipboardActionBundle
    from .actions.spotlight.bundle import SpotlightActionBundle
    from .actions.system.bundle import SystemActionBundle
    from .actions.user_io.bundle import UserIoActionBundle
    from .domains.finance.bundle import FinanceDomainBundle
    from .domains.deletion.bundle import DeletionDomainBundle
    from .domain_routes import DOMAIN_ROUTES

    for b in (TerminalActionBundle(), FilesActionBundle(), HostFilesActionBundle(),
              EmailActionBundle(), ApiActionBundle(),
              BrowserActionBundle(), MessageActionBundle(), CalendarActionBundle(),
              RemindersActionBundle(), NotesActionBundle(), ContactsActionBundle(),
              ClipboardActionBundle(), SpotlightActionBundle(), SystemActionBundle(),
              UserIoActionBundle()):
        registry.register_action_bundle(b)

    registry.register_domain_bundle(FinanceDomainBundle())
    registry.register_domain_bundle(DeletionDomainBundle())
    registry.register_domain_routes(DOMAIN_ROUTES)
```

## 9. Atomic Deletion List

### Already deleted

- `intentframe_native_bundles/manifest.py`
- `intentframe_native_bundles/policy_bridge.py`
- `intentframe_native_bundles/taxonomy.py`
- `intentframe_native_bundles/critical/` (entire folder)
- `intentframe_native_bundles/pre_pipeline.py` (top-level)
- `intentframe_native_bundles/types.py` (top-level; `BundleGateDecision` moved to SDK)
- `intentframe_native_bundles/registry.py` (top-level)
- `intentframe_native_bundles/evidence.py` (top-level; split into family folders)
- `intentframe_native_bundles/bundles/` (entire folder)
- `intentframe_native_bundles/passive_read/` (entire folder)
- `intentframe_native_bundles/actions/finance/` (finance is domain-only)
- `intentframe_bundle_sdk/constraint_checker_skip.py`
- Aggregator exports `CRITICAL_ACTIONS`, `PASSIVE_READ_ACTIONS`, `is_critical` from `intentframe_native_bundles/__init__.py`
- `NullActionBundle`, `CheckerOnlyActionBundle`, `gates()` shim, `_phase_to_result`, `constraint_type` field from `intentframe_bundle_sdk/action.py`
- `_CHECKER_BY_TYPE` map, `registered_checker_constraint_types()` from `intentframe_bundle_sdk/registry.py`
- `BundleContext.constraint_checker_skipped` field
- `ConstraintTypes` union from `policy_registry/models.py`
- `DomainConstraintTypes` from `policy_registry/models.py`

### Still to delete (Phase 6 remainder)

_None — completed 2026-05-24._

## 10. Phase-Wise Implementation

The work is structured as a sequence of phases, each independently mergeable and individually testable. Each phase ends with the test suite green and the substrate runnable.

### Phase 1 — SDK foundations (types, base classes, registry strictness) ✅

Scope:
- Add concrete `ActionPermission` dataclass and `copy_with_constraints()` helper in `intentframe_bundle_sdk/types.py`.
- Add `ConstraintPromptContext` dataclass.
- Add `BundleAIContext.constraint_context: ConstraintPromptContext | None`.
- Add `BundlePhaseOutcome.to_deterministic_result()` with the `matched_gate` passthrough.
- Move `BundleGateDecision` from `intentframe_native_bundles/types.py` into SDK types.
- Remove `BundleContext.constraint_checker_skipped`.
- Rewrite `intentframe_bundle_sdk/action.py`:
  - Remove all `intentframe_native_bundles` and `intentframe_components` imports.
  - New hook surface; rename `permission` to `action_permission`; drop `permission` from `prepare_evidence`, `enrich`, `structural_gates`.
  - `validate_constraints`, `enforce_constraints` default raise `NotImplementedError`.
  - `describe_constraints` default returns `None`.
  - Delete `NullActionBundle`, `CheckerOnlyActionBundle`, `gates()`, `_phase_to_result`, `constraint_type`.
- Rewrite `intentframe_bundle_sdk/domain.py` for `validate` + `enforce` + `describe`.
- Make registry strict in `intentframe_bundle_sdk/registry.py`:
  - Raise on empty `bundle_id`, empty `action_ids`, duplicate `action_id`, `passive_read_action_ids` not a subset of `action_ids`.
  - Drop `_CHECKER_BY_TYPE`, `registered_checker_constraint_types`, `NullActionBundle` fallback.
  - `action_bundle_for(action_id) -> ActionBundle | None`.
  - `all_action_bundles()`, `all_domain_bundles()`.
  - **Pass 12 routing (done):** `register_domain_routes`, `domains_for_action`, `registered_domain_ids`, `routed_domain_ids`, route-aware `validate_policy_domain_constraints`.
- Curate SDK exports.

Exit: ✅ SDK imports cleanly with no plugin imports.

### Phase 2 — Policy registry opaque dicts ✅

Scope:
- `ActionPermission.constraints: dict[str, Any] | None` in `policy_registry/models.py`; drop `ConstraintTypes`.
- `UserPolicy.domain_constraints: dict[str, dict[str, Any]]`; drop `DomainConstraintTypes`.
- Update `policy_registry/seeds/loader.py` to load constraints as raw dicts (no Pydantic validation at registry layer — bundles validate).
- Update `policy_registry/registry.py` merge helpers to operate on dicts.
- Update `intentframe_dashboard/__init__.py` lines 294–304 to raw-dict pass-through; drop `from policy_registry.domains import DOMAIN_CONSTRAINT_TYPES`.

Exit: ✅ Registry round-trips opaque dicts; dashboard renders policies; substrate boots.

### Phase 3 — Plugin family migration (fold + move constraints) ✅

Scope (one family at a time under `actions/`, in this order to minimize churn):

1. `actions/terminal/`: fold legacy bundle; move constraints to `actions/terminal/constraints.py`; `_capability_match.py`; evidence in `actions/terminal/evidence.py`.
2. `actions/files/`: fold + move `FileConstraints` and `FileIntel`.
3. `actions/host_files/`: fold + move `HostFileConstraints` (`FileIntel` shared from `actions/files/evidence.py`).
4. `actions/email/`: fold + move `EmailConstraints`.
5. `actions/api/`: first-class `ApiActionBundle` including `PAY_INVOICE`; move `ApiConstraints`.
6. `domains/finance/`: `FinanceDomainBundle` + plugin-local `FinanceConstraints` (no finance action family).
7. `actions/browser/`: first-class `BrowserActionBundle`; move `BrowserConstraints`.
8. `actions/message/`: first-class `MessageActionBundle`; move `MessageConstraints`.
9. `actions/calendar/`: full plugin; move `CalendarConstraints`; implement validate/enforce/describe.
10. `actions/reminders/`, `notes/`, `contacts/`, `clipboard/`, `spotlight/`, `system/`, `user_io/`: confirm action ownership; constraints only where YAML uses them.
11. `domains/deletion/`: `DeletionDomainBundle` + plugin-local `DeletionConstraints`.
12. `domain_routes.py`: declare `DOMAIN_ROUTES`; wire `register_domain_routes(DOMAIN_ROUTES)` in `register_bundles`.

For every bundle: implement `validate_constraints` (Pydantic `model_validate(...)`), `enforce_constraints` (parses fresh per call, no caching), and `describe_constraints` (or leave as default `None` to use SDK fallback).

Replace per-family `passive_read_action_ids` to match the locked list in Section 8.

Exit: ✅ Each family folder under `actions/` is the source of truth. Domain overlays live under `domains/` only. **Remaining:** delete duplicate top-level family folders and stale `policy_registry/constraints/` + `policy_registry/domains/` copies (Phase 6).

### Phase 4 — Runner wiring (passive-read gate + constraint prompt context + domain routing) ✅

Scope (`intentframe_bundle_sdk/runner.py`):
- Replace `check_policy` call with `enforce_constraints` (only when constraints present), with `NotImplementedError → BLOCK no_enforcement`.
- Deep-copy `action_permission.constraints` and wrap in `copy_with_constraints` before passing to the bundle.
- Resolve routed domains via `domains_for_action(action_id)`; loop all domains; deep-copy each `user_context.domain_constraints[domain_id]` slice and pass to `domain_bundle.enforce`.
- **Do not import `action_registry` or `ACTION_DOMAINS`** — routing is SDK registry authority.
- Insert the SDK passive-read ALLOW step strictly between `structural_gates` and `allow_gates`.
- Implement `build_constraint_prompt_context(bundle, action_permission, domain_ids, user_context)`:
  - Only called on the `UNDECIDED` path.
  - Calls `bundle.describe_constraints(action_permission)` with fallbacks per Section 6.
  - For each routed domain, calls `domain_bundle.describe(slice)` with fallback `f"{domain_id}: {slice}"`.
  - Returns a `ConstraintPromptContext` and attaches it to the bundle-supplied `BundleAIContext` via `dataclasses.replace`.
- Replace any reach-in to bundle internals with `BundlePhaseOutcome.to_deterministic_result()`.

Exit: ✅ Deterministic baselines green; UNDECIDED results carry populated `constraint_context`; multi-domain routing works.

### Phase 5 — Substrate cleanup (Guardian, deterministic gate, pipeline) ✅

Scope:
- `intentframe_components/guardian/engine.py`:
  - Delete `_check_constraints`, `_evidence_command_intel`, `_evidence_file_intel`, domain re-enforcement block.
  - Delete every import of `CONSTRAINT_CHECKERS`, `summarize_constraints`, and `action_bundle_for`/`domain_bundle_for` in the prompt path.
  - Replace constraint text resolution with a plain read of `bundle_ai_context.constraint_context.action_constraints` and `bundle_ai_context.constraint_context.domain_constraints`.
  - Keep `permission.safe` fast-path and `intent_limits` injection.
- `intentframe_components/guardian/deterministic.py`:
  - Block any allowed action with no registered bundle, `matched_gate="no_bundle"`.
  - Continue calling the temporary `_ensure_first_party_bundles_loaded()` shim from `intentframe_native_bundles/__init__.py` until Phase 7.
- `intentframe_server/pipeline.py`:
  - Pass `BundleAIContext` (including `constraint_context`) from the deterministic result straight to AE/Guardian.
  - Keep forensic audit dumping raw opaque constraints — that is acceptable substrate behavior.
- `intentframe_components/onboarding/engine.py`: switch manifest-driven listings to `all_action_bundles()`.
- `intentframe_native_bundles/onboarding/summarize_constraints.py`: delegate to `bundle.describe_constraints(action_permission)` with dict-dump fallback.

Exit: ✅ Guardian renders prompts from `BundleAIContext` data only. **Remaining:** delete dead `guardian/checkers/` package (Phase 6).

### Phase 6 — Atomic legacy scaffolding deletion ✅

Delete everything remaining in Section 9 ("Still to delete"). Do it in one wave because cross-references between these files would otherwise create dead imports.

Sub-steps:
- Migrate the 12+ test imports of `ensure_bundles_registered` / `_ensure_first_party_bundles_loaded` to a shared helper `tests/_bundle_loader.py` that calls `_ensure_first_party_bundles_loaded()` (in this phase) and `ensure_loaded(["intentframe_native_bundles"])` (in Phase 7).
- Delete `guardian/checkers/`, duplicate top-level family folders, `policy_registry/constraints/`, `policy_registry/domains/`.

Exit: ✅ workspace builds with no dead imports; tests pass via `tests/_bundle_loader.py`.

### Phase 7 — Loader and startup validation 🔲

Scope:
- Add `intentframe_bundle_sdk/loader.py` with `ensure_loaded(packages: list[str]) -> list[ActionBundle]`:
  - Idempotent.
  - For each package: `importlib.import_module(package)`; assert `register_bundles` is present; call `module.register_bundles(registry)`.
  - After all packages register, walk seeded `UserPolicy`:
    - For each allowed action with constraints, resolve bundle (must exist) and call `bundle.validate_constraints(action_permission)`.
    - For each domain in `domain_constraints`, resolve domain bundle, verify route exists, and call `domain_bundle.validate(slice)` (via `validate_policy_domain_constraints`).
  - Any failure → raise → substrate refuses to start.
- `intentframe_components/guardian/deterministic.py`: add `packages: list[str]` constructor arg; call `ensure_loaded(packages)`.
- `intentframe_server/server.py`: `_create_runtime()` constructs `DeterministicGuardian(packages=["intentframe_native_bundles"], verbose=verbose)`.
- Delete the `_ensure_first_party_bundles_loaded()` shim from `intentframe_native_bundles/__init__.py` (keep `register_bundles(registry)`).
- Update `tests/_bundle_loader.py` to call `ensure_loaded(["intentframe_native_bundles"])`.

Exit: loader is the single path that builds the registered bundle set; tests and substrate share that path; startup fails fast on bad policy shape.

### Phase 8 — Tests rewrite and verification 🔲 partial

**Already added:**
- `tests/test_domain_routes.py` — SDK routing, route-required validation, `PAY_INVOICE` on `ApiActionBundle`.
- `tests/test_deterministic_runner_order.py` — domain enforce before passive-read ALLOW.

Add or rewrite:
- Bundle hook signature snapshot: `inspect.signature(...)` for every loaded bundle hook matches the SDK contract; bundle hooks must never accept `UserContext`.
- Coverage invariants from seeded `UserPolicy`:
  - Every allowed action resolves to a bundle.
  - Every constrained action's bundle overrides `enforce_constraints` and `validate_constraints`.
  - Every domain in `domain_constraints` resolves to a domain bundle that overrides `validate` and `enforce`.
- BLOCK and startup-fail tests:
  - Allowed action with no bundle → BLOCK `matched_gate="no_bundle"`.
  - Constrained action without `enforce_constraints` override → BLOCK `matched_gate="no_enforcement"` at runtime.
  - Constrained action without `validate_constraints` override → loader raises at startup.
  - Bad-shape constraints → loader raises at startup via `validate_constraints`.
  - Duplicate `action_id` registration → `ValueError`.
  - Empty `bundle_id` / empty `action_ids` → `ValueError`.
  - `passive_read_action_ids` not a subset → `ValueError`.
  - Package missing `register_bundles` → loader raises `ImportError`.
- Runner constraint prompt context tests:
  - UNDECIDED with constraints → `BundleAIContext.constraint_context.action_constraints` is set; `describe_constraints` was called once in the runner.
  - Terminal ALLOW/BLOCK results → `constraint_context` is `None`.
  - Missing description → fallback `str(action_permission.constraints)` populated by the runner.
  - Routed domain → `constraint_context.domain_constraints` includes the domain's rendered string.
- Runner order test: `structural_gates → SDK passive_read → allow_gates`.
- Component boundary tests:
  - `AIGuardian` source has no `CONSTRAINT_CHECKERS`, `action_bundle_for`, `domain_bundle_for`, `describe_constraints`, `domain_bundle.describe`, `summarize_constraints` references.
  - Guardian prompt builder renders only from `BundleAIContext.constraint_context` data.
- `BundlePhaseOutcome.to_deterministic_result()` tests:
  - `matched_gate="command_shield"` → `decision_path="command_shield"`.
  - `matched_gate=""` or unset → `decision_path="deterministic"`.
- Mutation-safety test: bundle mutating `action_permission.constraints` does not affect host-cached policy.
- Update `tests/test_policy_host_constraints_roundtrip.py` for dict storage.
- Update `tests/test_bundle_constraint_registry.py` from checker-coverage to bundle/action coverage.
- Update `tests/test_prompt_strategy.py` to remove the `CRITICAL_ACTIONS ∩ PASSIVE_READ_ACTIONS == ∅` aggregate drift guard (strict registry handles uniqueness).
- Delete `tests/test_constraint_checker_skipped.py`.
- Replace any remaining test that imports `PassiveReadActionBundle` or `intentframe_native_bundles/passive_read/`.

Baseline parity:
- ✅ `tests/fixtures/hardened_prompts_*` and `deterministic_gate_matrix_*` baselines green after Phases 1–5 routing restoration.

Exit: Full test suite green with new invariants in place.

### Phase 9 — Documentation, conventions, and risk closure 🔲

Scope:
- Add module-level docstrings for the new conventions:
  - Async vs sync: I/O only in async hooks; pure compute is sync.
  - Bundles never see `UserContext`, `UserPolicy`, or other actions' policy.
  - No caching of parsed constraints across calls (supports hot reload).
  - Runner is the sole runtime caller of bundle/domain hooks; components consume `BundleAIContext`.
  - `register_bundles(registry)` is the only required public entry point per plugin package; no module-level side effects on import.
- Update onboarding docs and any developer-facing references that still mention `bundles/`, `manifest.py`, or `passive_read` bundle.
- Sync the canonical plan from `/Users/prince/.cursor/plans/bundle_sdk_plugin_refactor_v5_bb174813.plan.md` into the workspace `.cursor/plans/` directory and mark the older v3/v4 plan files as superseded (or delete them). Future agents must follow only the v5 file.

Exit: contributors can read the SDK docstrings and follow the contract without consulting old plan files.

## 11. Risks and Follow-Ups

- Forensic audit switches from typed Pydantic repr to dict repr; existing prompt parity tests are expected to still pass because the legacy Guardian fallback was `str(permission.constraints)` anyway, but if drift appears, do a controlled baseline regeneration as a follow-up.
- External Jarvis YAML schema stays unchanged (`intentframe_schema_version: 1`); only bump if dict migration breaks a seeded YAML in practice.
- Action-id namespacing is intentionally out of scope; the strict-duplicate `ValueError` is the only collision defense.
- Policy hot reload: bundles parse on each call; absence of cache state on bundle classes is enforced by convention and reviewed in PR (no automated lint added for this).
- `pyproject.toml` entry points are deliberately not added; loader is constructor-arg driven.
- Pass-10 already wired `passive_read_action_ids` and the SDK gate, and pass-11 already removed the critical/taxonomy aggregator. Phase 3 must reconcile these against the final layout — do not recreate `passive_read/` as a final family.

## 12. What Is Locked (Single-Decision Summary)

| # | Decision |
|---|----------|
| Loader config | Constructor arg only; `DeterministicGuardian(packages=[...])`; server passes list. |
| Startup validation | Dedicated `validate_constraints` on `ActionBundle` and `validate` on `DomainBundle`; loader fails fast. |
| Calendar | Full new plugin with bundle + constraints + enforce + validate + describe. |
| Critical/Passive aggregation | Deleted entirely; per-family local sets. |
| api/browser/message ids | Real action ids per `action_registry/types.py`; no families dropped. |
| `api` vs `finance` | `ApiActionBundle` owns `PAY_INVOICE`, `HTTP_GET`, `HTTP_POST`, …; finance is domain-only (`domains/finance/`). No `FinanceActionBundle`. |
| Domain routing | `domain_routes.py` + `register_domain_routes()`; runner uses `domains_for_action()`; not `ACTION_DOMAINS`. |
| `ACTION_DOMAINS` | Kept in `action_registry/types.py` for actor/demo/docs only; not imported by SDK runner. |
| `_capability_match.py` | `intentframe_native_bundles/actions/terminal/_capability_match.py`. |
| `_to_result` / `decision_path` | `BundlePhaseOutcome.to_deterministic_result()`; `matched_gate` passthrough, else `"deterministic"`. |
| Dashboard `DOMAIN_CONSTRAINT_TYPES` | Raw dict pass-through. |
| Dashboard manifest flags | No replacement; vanish with `manifest.py`. |
| `policy_bridge.py` | Delete (zero external consumers). |
| `pyproject.toml` entry points | Not added. |
| Mutation safety | Runner deep-copies constraints; bundles parse fresh each call. |
| Test drift guards | Aggregate `CRITICAL_ACTIONS ∩ PASSIVE_READ_ACTIONS == ∅` removed; strict registry covers uniqueness. |
| Passive-read gate | SDK runner owns it; runs between `structural_gates` and `allow_gates`; uses `bundle.passive_read_action_ids` + `action_permission.safe`. |
| Constraint prompt boundary | Runner builds `ConstraintPromptContext` on `BundleAIContext`; components consume plain data only; fallbacks live in the SDK runner. |
| Description timing | Runner calls describe hooks only for `UNDECIDED` paths; terminal ALLOW/BLOCK do not build constraint prompt context. |

---

That is the full combined plan. **Phases 1–9 are complete.**