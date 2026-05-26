# Substrate Plugin Refactor — Goals, Decisions, and Outcome

**Status:** Complete on branch `refactor-substrate` (merged PR #33, `d191b6e`). Post-merge follow-up (`88d61f6`–`8600ec8`, May 2026) decoupled remaining policy-registry business logic (terminal system floor, contact resolution, constraint schemas) into native bundles.  
**Legacy baseline:** `66e567c` (pre-refactor tag)  
**Canonical implementation plan:** `TODO/new_plan.md`  
**Developer runbook:** [dev/action-family-wiring.md](../dev/action-family-wiring.md)

This document captures **why** the substrate was refactored, **what** changed, **what was debated** in design sessions (May 22–24, 2026), and **how** we know behavior was preserved. It is the internal narrative companion to the module map in [modules.md](../modules.md).

For industry survey of future partner extension formats (MCP, WASM, Cedar, etc.), see [action-wiring-refactor.md](action-wiring-refactor.md) — that file is forward-looking strategy, not a record of this refactor.

---

## 1. High-level goal

Turn IntentFrame from a **monolithic, action-hardcoded substrate** into a **strict plugin platform** suitable for B2B deployment:

- **Substrate** (`intentframe_components/`, `intentframe_server/`) orchestrates the pipeline and consumes prepared data. It must not encode action-family field names, re-run enforcement at prompt-build time, or dispatch into per-family checkers.
- **Bundle SDK** (`intentframe_bundle_sdk/`) owns the lifecycle contract, fixed gate order, registry, loader, and data shapes flowing to AI layers.
- **Plugins** (`intentframe_native_bundles/`) own action ids, constraint schemas, evidence, validation, enforcement, descriptions, structural/allow gates, and AI context.
- **Policy registry** stores **opaque dict** constraints only — no typed constraint unions that couple core modules to plugin schemas.

The refactor was triggered initially by wanting **permission before shield** in the deterministic path, but the actual work became a full **bundle SDK + plugin migration** because the old architecture mixed three roles in one place (SDK hooks, legacy manifest/checker dispatch, and substrate re-enforcement).

---

## 2. What problem we were solving

Before refactor (`66e567c`), deterministic policy lived in several overlapping places:

| Location | Role |
|----------|------|
| `intentframe_server/pipeline.py` | command_shield, file_intel, email enrich **before** DG |
| `intentframe_components/guardian/deterministic.py` | permission, CONSTRAINT_CHECKERS, DOMAIN_MODULES, path floors, passive/read-only ALLOW |
| `intentframe_components/guardian/checkers/` | Per-family checker dispatch |
| `intentframe_components/guardian/engine.py` | Re-summarized constraints via checkers at Guardian prompt time |
| `intentframe_action_bundle/manifest.py` | Duplicate metadata + checker registry bridge |

This caused:

- **Boundary violations** — SDK imported substrate checkers; Guardian re-ran logic the runner already ran.
- **Drift risk** — same gate implemented in pipeline, DG, and sometimes AE.
- **Poor extensibility** — adding an action family required edits across ~15 unrelated files with no compiler-enforced relationship.
- **Confusion** — two “bundle systems” (manifest/checkers vs SDK lifecycle) active at once.

---

## 3. Target architecture (current)

```
Policy YAML → policy_registry (opaque dicts)
                    ↓
Server boot → DeterministicGuardian(packages=[...])
                    ↓ ensure_loaded() + validate_policy_against_registry()
DeterministicRunner (SDK) — fixed gate order:
  permission
  → prepare_evidence   (command_shield, file_intel, …)
  → enrich             (email resolve, …)
  → enforce_constraints
  → domain.enforce     (per domains_for_action)
  → structural_gates   (path/floor BLOCKs)
  → passive_read ALLOW (SDK-owned)
  → allow_gates        (e.g. terminal read-only ALLOW)
  → UNDECIDED + BundleAIContext → AE → Guardian → Executor
```

### Layer responsibilities

| Layer | Owns | Must not |
|-------|------|----------|
| Substrate | UserPolicy resolution, pipeline, AE/Guardian assembly, audit | Read constraint field names; call checkers; import plugin schemas |
| Bundle SDK | Hook contract, runner order, registry, loader, `BundleAIContext` | Import first-party evidence types or substrate checkers |
| Plugins | Action/domain logic, constraints, enforcement, AI context | See `UserPolicy` or other actions' permissions |
| Policy registry | Storage of opaque dicts only | Typed Pydantic constraint unions; system-floor merge; contact-source resolution; constraint shape validation |

### Package layout

```
intentframe_native_bundles/
  actions/<family>/     # ActionBundle implementations
  domains/<domain>/     # DomainBundle implementations (finance, deletion)
  platform/             # Shared runtime helpers (e.g. contacts_client for policy sources)
  domain_routes.py      # domain_id → action ids (routing manifest)
  onboarding/           # first-party onboarding copy
  __init__.py           # register_bundles(registry) only
```

Three concepts stay **separate** (do not collapse):

1. **Action bundles** — own action ids and action-level constraints.
2. **Domain bundles** — own domain logic only; no action ids.
3. **Domain routes** — routing metadata via `register_domain_routes()`.

---

## 4. What was done (by phase)

Implementation followed nine phases in `TODO/new_plan.md`, grouped into four **waves** during execution:

| Wave | Phases | Summary |
|------|--------|---------|
| A+B | 1–5 | SDK foundations, opaque policy dicts, family migration, runner wiring, substrate cleanup |
| C | 6 | Delete legacy scaffolding (checkers, manifest, policy_registry/constraints, policy_registry/domains) |
| D | 7–9 | Loader, invariant tests, documentation |

### Key commits (since `66e567c`)

| Commit | Milestone |
|--------|-----------|
| `9ee1096` | Init substrate refactor — action bundle package, checkers, manifest |
| `0da0193` | Bundle SDK + DeterministicRunner introduced |
| `5154eb5` | Prompt refactor — `intentframe_prompt_library`, bundle `build_ai_context` |
| `5719a35` | Pass 12 — domain SDK, `register_domain_routes`, many-to-many routing |
| `eb1a4e3` | Passive-read on per-bundle `passive_read_action_ids`; `allow_gates` |
| `551229e` | Rename → `intentframe_native_bundles` |
| `e3855aa` | Fix actions/ vs domains/ split |
| `aeb3130` | Restore pass-12 SDK routing; delete policy_registry constraint copies |
| `fee09a6` | Loader + invariant tests (pass 15) |
| `88d61f6` | Decouple email/message contact resolution + terminal capabilities from policy registry |
| `0c27a38` | Policy registry cleanup — opaque CRUD only |
| `8600ec8` | Document future bundle-runtime validation contract (`policy_registry/TODO/bundle_validator.md`) |

### Deleted (legacy scaffolding)

- `intentframe_components/guardian/checkers/`
- `intentframe_action_bundle/` (entire package — replaced by native bundles + SDK)
- `policy_registry/constraints/`, `policy_registry/domains/`, `policy_registry/source_types.py`, `policy_registry/contacts_client.py`
- Terminal system-floor merge and `DEFAULT_TERMINAL_DENY_CAPABILITIES` ownership moved to `intentframe_native_bundles/actions/terminal/`
- Manifest, policy_bridge, NullActionBundle, checker shims

---

## 5. Deterministic gate parity with legacy

The refactor **re-homed** gates into SDK runner + plugins; it did **not** strip deterministic checks (except payload-based ALLOW heuristics, which were already absent at `66e567c`).

### Legacy DG inner order (`66e567c`)

```
1  permission
2  constraint (CONSTRAINT_CHECKERS)
2.5 domain (DOMAIN_MODULES)
3  write_file_sensitive_path
3b write_host_file_floor / delete_host_file_floor
4  passive_read ALLOW
5  run_command_read_only ALLOW
6  UNDECIDED
```

Pipeline **before** DG: command_shield, file_intel, email enrich.

### Current order (allowed actions)

```
permission (+ no_bundle)
→ prepare_evidence  ← was pipeline L2/L2b
→ enrich            ← was pipeline pre-DG
→ enforce_constraints  ← legacy step 2
→ domain.enforce       ← legacy step 2.5
→ structural_gates     ← legacy steps 3 + 3b
→ passive_read ALLOW   ← legacy step 4
→ allow_gates          ← legacy step 5
→ UNDECIDED            ← legacy step 6
```

### Gate mapping

| Legacy `matched_gate` | Today |
|----------------------|--------|
| `permission` | `DeterministicGuardian` |
| `constraint` | `bundle.enforce_constraints()` |
| `domain` | `domain_bundle.enforce()` |
| `command_shield` | `TerminalActionBundle.prepare_evidence()` |
| `write_file_sensitive_path` | `FilesActionBundle.structural_gates()` + `path_heuristics` |
| `write_host_file_floor` / `delete_host_file_floor` | `HostFilesActionBundle.structural_gates()` |
| `passive_read` | SDK `_try_passive_read_allow()` |
| `run_command_read_only` | `TerminalActionBundle.allow_gates()` |

**Verification:** Golden fixtures PASS as of pass 15:

- `tests/fixtures/hardened_prompts_*` — 12/12 prompt sections vs legacy `ee04d7f`
- `tests/fixtures/deterministic_gate_matrix_*` — 9/9 gate rows vs legacy `66e567c`

### Intentional deltas (not bugs)

| Topic | Legacy | Current | Why |
|-------|--------|---------|-----|
| Permission vs shield | Shield in pipeline **before** permission | Permission **first**, shield in `prepare_evidence` | Requested change |
| DG exceptions | UNDECIDED → AI | BLOCK fail-closed (`matched_gate=exception`) | Safer production posture |
| Missing bundle / enforcement | Could fall through quietly | `no_bundle` / `no_enforcement` BLOCK + startup validation | Fail-closed |
| Guardian constraint text | Checker `summarize()` at prompt time | Runner-built `constraint_context` on UNDECIDED path only | Single source of truth |
| AIGuardian re-checking DG | Redundant defense-in-depth | Thin — reads `BundleAIContext` only | Remove duplication |

---

## 6. Policy boundary decisions (from design discussions)

These were debated repeatedly across transcripts (May 22–24, 2026). See §7 for transcript index.

### Runner sees policy; bundles see slices only

- **DeterministicRunner** receives `UserContext` (for domain slices + routing).
- **ActionBundle** hooks receive `ActionPermission(safe, constraints dict)` — deep-copied per call.
- **DomainBundle.enforce** receives one `domain_constraints[domain_id]` dict slice.
- Bundles **never** receive `UserPolicy`, `UserContext`, or other actions' permissions.

### No YAML “family” layer

Bundles declare `action_ids`; policy YAML stays flat under `allowed_actions`. Duplicate `action_id` registration raises `ValueError`.

### Enforce vs describe (not checker vs summarizer)

| Job | Hook | Affects decision? |
|-----|------|-------------------|
| Deterministic enforcement | `enforce_constraints`, `domain.enforce` | Yes |
| AI prompt context | `describe_constraints`, `domain.describe` | No — UNDECIDED path only |
| Fallback if no describe | `str(constraints)` | Parity with legacy Guardian |

### Policy registry stores opaque dicts

Plugins own Pydantic validation via `validate_constraints` at startup and `enforce_constraints` at runtime. Registry is storage, not schema authority.

### Structural gates vs domain enforce

- **Domain enforce** — cross-cutting overlays (finance, deletion) on routed actions.
- **Structural gates** — path/floor BLOCKs that do not depend on user's constraint dict (sensitive virtual paths, host deny floors).

### Heuristics package

Legacy `intentframe_components/heuristics/` (`is_sensitive_write_path`, `classify_path_category`) moved to `actions/files/path_heuristics.py`. Still used for **BLOCK-only** deterministic gates and file_intel context — not for payload ALLOW shortcuts (removed before `66e567c`).

---

## 7. Discussion themes (transcript index)

Questions and concerns raised during the refactor (May 22–24, 2026). Agent transcript UUIDs are Cursor session IDs.

| Theme | Transcript UUID (Cursor agent session) |
|-------|----------------------------------------|
| Overall refactor goal, policy slices, manifest removal | [70f4ca49](70f4ca49-38c0-451a-a585-6c2c62489ac0) — export: `cursor_1_final_conclusions_from_chat_t.md` |
| Prompt/context refactor, action-agnostic SDK, trusted sections | [ad0e3534](ad0e3534-9965-4a08-8dfe-7e221262e9d6) — export: `cursor_1_planning_changes_for_agent_tr.md` |
| PR A/B, heuristics, substrate cleanup | [e1b64cb7](e1b64cb7-bffb-42dc-9528-ebb61593b7d2) — export: `cursor_substrate_action_semantics_and_b.md` |
| Runner order, enrichment, final audits | [d333d589](d333d589-32c7-461a-a1f4-034d48125145) — export: `cursor_code_review_and_audit_for_refact.md` |
| Pre-merge checklist, exceptions, missing checker | [0e1554bc](0e1554bc-58ba-45a0-a599-bcf375ecc461) — export: `cursor_refactoring_assessment_and_confi.md` |
| Waves A/B/C/D, pass 12 regression, domain/action split | [acd4e302](acd4e302-30b7-4f3a-a622-31bc229f2b74) — export: `cursor_plan_for_combining_project_phase.md` |
| Loader, boundary audit, parity | [6f8023fa](6f8023fa-1a8a-4644-8f6f-94a2751c9dc5) |
| Passive read, file folders, critical/ removal | [d573ca9f](d573ca9f-be8f-433e-a506-a7133dfc390f) |
| Guardian duplication, enforce/describe split | [0888e711](0888e711-7f6d-4514-bf70-54cea6d891a7), [41d3abd7](41d3abd7-ba00-47d0-84df-86f836eb7d4e) |

### Recurring founder concerns (and resolutions)

1. **“Substrate should not know action names or keywords”** — Largely achieved in production code; minor leaks remain in onboarding (`native_bundles.onboarding`) and email enricher import. Stale TODO docs may still reference old paths.

2. **“Why two bundle systems?”** — Resolved by Wave C deletion. One system: SDK + `register_bundles`.

3. **“Pass 12 concepts lost in later passes”** — Restored in `aeb3130`: `domains_for_action`, `_ROUTED_DOMAIN_IDS`, route-aware validation, no runner import of `ACTION_DOMAINS`.

4. **“Domain bundles importing action constraints”** — Fixed: domains use `domains/*/constraints.py` only.

5. **“Tests rigged?”** — No; golden baselines frozen at legacy commits. Some tests retargeted when behavior intentionally moved (e.g. shield inside runner).

6. **“Was only permission reorder requested?”** — Yes as trigger; full plugin refactor was the agreed scope to avoid throwaway intermediate shims.

---

## 8. Hook surface (final contract)

```python
class ActionBundle:
    startup → prepare_evidence → enrich → validate_constraints (startup)
    → enforce_constraints → structural_gates → allow_gates
    → build_ai_context + describe_constraints (UNDECIDED path)
    → onboarding_guardrails() (onboarding handshake only — not in hot path)
    → aclose (shutdown)

class DomainBundle:
    startup → validate (startup) → enforce → describe (UNDECIDED path)
    → aclose (shutdown)
```

Gate order is **owned by DeterministicRunner** — authors do not override ordering.

Loader entry point per plugin package:

```python
def register_bundles(registry) -> None: ...
```

Boot: `ensure_loaded(["intentframe_native_bundles"])` then `validate_policy_against_registry(policy)`.

---

## 9. Remaining cleanup (non-blocking)

| Item | Notes |
|------|-------|
| Orphan copies under `intentframe_native_bundles/{files,terminal,...}/` (top-level, not under `actions/`) | Not imported; safe to delete |
| `onboarding/engine.py` imports native onboarding | ~~Optional decouple~~ — Done: `engine.py` now imports `build_onboarding_instructions` from `intentframe_components.onboarding.instructions`. Bundle SDK owns the middle section via `render_onboarding_bundle_context`; each bundle contributes via `onboarding_guardrails()`; cross-bundle copy lives in `intentframe_native_bundles/onboarding/manifest.py`. |
| ~~`intentframe_server/enrichers/email.py` imports native enrich~~ | Done — bundle owns `EmailClient` lifecycle via `aclose()` |
| `policy_registry/seeds/loader.py` calls `ensure_loaded()` | Resolved: loader validates constraint shapes via `validate_policy_against_registry` after opaque `UserPolicy` construction. Registry HTTP writes remain unvalidated until bundle-runtime service lands (see `policy_registry/TODO/bundle_validator.md`). |
| `intentframe_components/TODO/*.md` | References pre-refactor paths (criticality, strategy.py) |
| Commit `TODO/new_plan.md` | Plan doc still untracked in some snapshots |

---

## 10. How to verify after future changes

```bash
# Gate matrix parity (66e567c baseline)
uv run pytest tests/test_deterministic_gate_matrix.py -v

# Prompt parity (ee04d7f baseline)
uv run pytest tests/test_hardened_prompts_parity.py -v

# SDK invariants
uv run pytest tests/test_bundle_sdk_invariants.py tests/test_bundle_loader.py -v

# Full suite (excluding sandbox)
uv run pytest tests/ -q --ignore=tests/sandbox
```

If a change alters deterministic outcomes, update baselines **deliberately** with documented reason — do not weaken tests to pass.

---

## 11. Related documents

| Document | Purpose |
|----------|---------|
| [TODO/new_plan.md](../../TODO/new_plan.md) | Phase-wise implementation plan (status table) |
| [dev/action-family-wiring.md](../dev/action-family-wiring.md) | Checklist for adding action families |
| [modules.md](../modules.md) | Module map including bundle SDK + native bundles |
| [action-wiring-refactor.md](action-wiring-refactor.md) | Industry patterns for future partner extensions |
| `intentframe_components/TODO/substrate_vocabulary_hygiene.md` | Optional zero-literal cleanup backlog |

---

*Last updated: 2026-05-26 — onboarding decoupled from native bundles (refactor-substrate branch); `engine.py` cleanup item resolved.*
