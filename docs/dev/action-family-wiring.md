# Action Family Wiring Map

Status: **developer runbook**. Use this when adding, auditing, or debugging a family of actions (e.g. `FILE`, `HOST_FILE`, `TERMINAL`, `EMAIL`).

This document exists because the IntentFrame pipeline legitimately has many layers (policy, deterministic guardian, analysis engine, AI guardian, executor, onboarding, agent handshake), and a single new action fans out to ~15 files. Most of those files do not reference each other, so drift is silent: code builds green, tests pass, and the only symptom is that something quietly does not reach production at runtime — e.g. the agent advertises a tool the policy does not grant, or the onboarding prompt never mentions a capability the agent actually has.

Read this before adding a new action family. Read it again when you are debugging "why isn't X being enforced / mentioned / routed the way I expect?".

---

## Mental model in one paragraph

An agent submits an intent. It travels through several gates. Each gate is independent, each has its own opinion, and any of them can block. If the intent survives, the executor adapter performs the real I/O. Onboarding, handshake, and tool descriptions are the things the LLM sees; everything else is runtime enforcement the LLM never sees directly. The trick is that the LLM's picture of the world is built from **declarations** (tool docstrings, `AgentCapabilities.action_types`, onboarding guardrails), while enforcement is built from **different declarations** (`ActionType` enum in bundles/packs, policy YAML allowed actions, bundle constraint schemas, domain routes). When those two sets of declarations drift, the agent sees capabilities the runtime blocks (or vice versa).

**Three declaration layers for actions:**

| Layer | Who | What |
|---|---|---|
| Core / Actor | Platform | `IntentFrame.action` is a plain `str`; Actor does not import `action_registry` |
| Agent author (optional) | Jarvis, third-party agents | May import `action_registry` + per-tool Pydantic models for fail-fast pre-flight |
| Substrate | Bundles, executor, policy | `ActionType` constants, `domain_routes.py`, bundle constraints — authoritative at runtime |

---

## The two vocabularies

Before touching anything file-path-related, be explicit about which world you are in:

| Vocabulary | Example | Canonicalizer | Checker | Constraint type |
|---|---|---|---|---|
| Virtual filesystem | `/home/foo.txt` | `normalize_virtual_path` | `FileChecker` | `FileConstraints.allowed_paths` |
| Host filesystem | `~/Documents/foo.txt` | `canonicalize_real_path` | `HostFileChecker` | `HostFileConstraints.allowed_host_paths` |

The two must **never** share a constraint field name. The disjoint field names (`allowed_paths` vs `allowed_host_paths`) must not be renamed or unified.

Trailing-slash shorthand for host paths (`~/Documents/`) is rejected at config load time. Use `dir/*` for subtree scope, exact paths otherwise.

For runtime enforcement, supporting both vocabularies is fine. For
LLM-facing product design, it usually is **not**. In real agent
profiles, prefer exposing either the VFS family or the host-file family,
not both. The dedicated design note is
`docs/vfs-vs-host-tools.md`.

---

## The wiring fan-out (checklist for a new action family)

A "family" is a set of related actions that share a category, a checker, a constraint type, and an adapter (e.g. `HOST_FILE` = `READ_HOST_FILE` + `WRITE_HOST_FILE` + `DELETE_HOST_FILE` + `LIST_HOST_DIRECTORY`).

When adding one, expect edits in roughly these places. Missing any of them produces a specific silent failure listed in the Symptoms table at the bottom.

### 1. Action type + category

- `action_registry/types.py` — add `ActionType.<NAME>` entries and map them to a new or existing `ActionCategory`.
- `action_registry/catalog.py` / `action_registry/platforms/<os>/actions.py` — register the new actions in the catalog so adapters can claim them.

### 2. Executor adapter

- `executor/platforms/<os>/adapters/<family>.py` — implement `supported_actions()`, `manifest()`, and `execute()`.
- `executor/config/schema.py` — if the family needs config (allowed paths, blocked patterns, etc.), add a typed config block and attach it to `ExecutorConfig`.
- `executor/config/executor.yaml` (and every downstream YAML: `demo/config/executor.yaml`, `demo/config/executor_attacks.yaml`, `jarvis_pa/executor.yaml`) — add the config section.

### 3. Plugin constraint schemas (policy storage stays opaque dicts)

- `intentframe_native_bundles/actions/<family>/constraints.py` — Pydantic models for action-level constraints (`FileConstraints`, `TerminalConstraints`, …). Use **disjoint field names** across families so validation is unambiguous.
- `intentframe_native_bundles/domains/<domain>/constraints.py` — domain overlay schemas (`FinanceConstraints`, `DeletionConstraints`).
- `policy_registry/models.py` — stores `ActionPermission.constraints` and `UserPolicy.domain_constraints` as opaque dicts only; no typed constraint unions in the registry layer.
- `intentframe_bundle_sdk/loader.py` — single boot path: `ensure_loaded(packages)` registers bundles, then `validate_policy_against_registry(policy)` calls each bundle's `validate_constraints` / domain `validate` at startup.

### 4. Bundle SDK + deterministic gate

- `intentframe_bundle_sdk/` — `ActionBundle` / `DomainBundle` hook contract, `DeterministicRunner` (fixed gate order), registry + domain routes.
- `intentframe_native_bundles/domain_routes.py` — routing manifest (`domain_id` → action ids); registered via `register_domain_routes`.
- `intentframe_components/guardian/deterministic.py` — permission gate + `DeterministicRunner`; blocks `no_bundle` / `no_enforcement`.
- `intentframe_components/guardian/engine.py` — AI Guardian reads `bundle_ai_context.constraint_context` only (no checker dispatch).
- `resource_registry/floor.py` — if this family writes to the host filesystem, extend `DENY_WRITE_PREFIXES` with any non-negotiable deny roots.

### 5. Bundle lifecycle hooks (evidence, AI context, gates)

Post-refactor, family-specific deterministic and prompt logic lives on the **ActionBundle**, not in substrate checkers or pipeline pre-hooks.

- `intentframe_native_bundles/actions/<family>/bundle.py` — implement hooks as needed:
  - `prepare_evidence()` — e.g. command_shield BLOCK, file_intel (terminal/files)
  - `enrich()` — e.g. email intent resolution
  - `enforce_constraints()` — policy constraint enforcement
  - `structural_gates()` — path/floor BLOCKs (files, host_files)
  - `allow_gates()` — custom ALLOW fast paths (e.g. terminal read-only)
  - `build_ai_context()` — AE system instructions + external context string
  - `describe_constraints()` — optional; runner fallback is `str(constraints)`
  - `startup()` / `aclose()` — optional; open and release bundle-owned external resources (IMAP clients, pools, background tasks). Must be idempotent. The runtime calls `startup_bundles()` / `shutdown_bundles()` on boot/shutdown; substrate never imports plugin modules directly.
- `passive_read_action_ids` on the bundle — SDK-owned passive-read ALLOW (declare subset of `action_ids`)
- `intentframe_prompt_library/` — substrate default prompt fragments; bundles override via `build_ai_context()`
- See [\_internal\_/substrate-plugin-refactor.md](../_internal_/substrate-plugin-refactor.md) for gate order vs legacy `66e567c`.
- Resource audit: `tests/test_native_bundles_resource_audit.py` guards against module-level client singletons. Only `email` owns an external client today; `browser`, `api`, `host_files`, and `terminal` are pure constraint/evidence bundles with default no-op `aclose()`.
- Future multi-resource bundles: see the ``AsyncExitStack`` note in `intentframe_bundle_sdk/action.py`.

### 6. Agent + onboarding (LLM-visible surface)

- `jarvis_pa/jarvis/tools.py` — add `function_tool` wrappers whose
  docstrings are self-contained for the granted family. Avoid
  cross-referencing sibling file families unless you are intentionally
  building a comparison/test profile.
- `jarvis_pa/jarvis/agent.py::_ACTION_TYPES` — add the new action types so they appear in `AgentCapabilities` at handshake.
- `intentframe_native_bundles/actions/<family>/onboarding_guardrails.py` — implement the `onboarding_guardrails()` function and wire it in the bundle's `onboarding_guardrails()` override. Return a paste-ready markdown block (e.g. `### Email Actions (...)`) that the onboarding meta-LLM will see in the system-prompt middle section. Return `""` if the family has no onboarding copy of its own.
- `intentframe_native_bundles/onboarding/manifest.py` — if the family participates in a **cross-bundle rule** (e.g. a guardrail that only makes sense when two families are both active), add a verbatim string to `ONBOARDING_MANIFEST.sections`. This is appended unconditionally to the middle section for all policies.
- `tests/test_onboarding_sdk.py` — add a test asserting the bundle section appears in `render_onboarding_bundle_context` when its actions are granted, and is absent when they are not.
- `tests/fixtures/onboarding/bundle_sections/<bundle_id>.txt` — run `python tests/inspect_onboarding_prompts.py --write-baseline` to regenerate golden fixtures after intentional content changes.

### 7. Policy seed (the runtime truth)

The default Jarvis policy lives in YAML at `jarvis_pa/jarvis/policies/<variant>.yaml`
and is loaded by `policy_registry.seeds.load_policy_seed`. Both the
gateway bootstrap and the dev seed CLI go through that one loader, so
there is exactly one place to edit per variant:

- `jarvis_pa/jarvis/policies/jarvis.yaml` — user-mode Jarvis (host paths `~/*`, `agent_id: jarvis`).
- `jarvis_pa/jarvis/policies/jarvis_root.yaml` — root-mode Jarvis (host paths `/*`, `agent_id: jarvis_root`).
  Mirror the user variant except for the host-path scope and the
  `agent_id`; both YAMLs must keep the same
  `RUN_COMMAND.deny_capabilities` set (pinned by `tests/test_seed_capability_parity.py`).
- `intentframe_gateway/bootstrap.py` — orchestrator. Adds runtime
  overlays (`user_id` from gateway config, `agent_id` from the resolved
  Jarvis variant, `metadata.note` stamp) and POSTs to the policy +
  resource registries. The legacy `SAFE_ACTIONS`, `UNSAFE_ACTIONS`,
  `INTENT_LIMITS`, `_build_default_policy()`, and `_build_jarvis_policy(...)`
  symbols are preserved as derived re-exports so external callers keep
  working; edit the YAML, not these.
- `jarvis_pa/seed_policies.py` — thin dev CLI on top of the same
  loader. Idempotent (GET-first, skip if present). Variant-aware via
  `JARVIS_VARIANT` (default `user`).

End users override either Jarvis variant by dropping a YAML at
`~/.intentframe/policies/<agent_id>.yaml` (e.g.
`~/.intentframe/policies/jarvis.yaml`); the loader picks it up on
next gateway restart.

### 8. Tests

- `tests/test_bundle_constraint_registry.py` — every seeded allowed action resolves to a bundle; constrained actions override `enforce_constraints`.
- `tests/test_bundle_loader.py` / `tests/test_bundle_sdk_invariants.py` — loader fail-closed, registry strictness, runner prompt context, substrate boundary.
- `tests/test_deterministic_guardian.py` — any new gate (passive read, write floor, delete floor).
- `tests/test_prompt_strategy.py` — prove the new actions route to the expected prompt lane.
- `tests/test_<family>_adapter.py` — executor-side path handling.
- `tests/test_jarvis_host_scope_mirror.py` or equivalent — pin the invariant between `executor.yaml` and `bootstrap.py` for this family if there is one.

---

## Drift hotspots (where silent failure lives)

These are the files that **must** stay in sync but have no compiler-enforced relationship. Every one of these has bitten us at least once.

| Pair | What drifts | Symptom |
|---|---|---|
| `jarvis_pa/jarvis/policies/jarvis.yaml::allowed_actions` ↔ `ActionType` enum | YAML missing new actions | Handshake total count is lower than enum size; agent sees tool, policy denies at runtime |
| `jarvis_pa/jarvis/agent.py::_ACTION_TYPES` ↔ `tools.py::ALL_TOOLS` | Agent advertises fewer actions than it can call | Onboarding prompt has no guardrails for the missing actions; agent still calls them, no policy-side guidance |
| `jarvis.yaml::RUN_COMMAND.deny_capabilities` ↔ `intentframe_native_bundles.actions.terminal.capabilities.DEFAULT_TERMINAL_DENY_CAPABILITIES` | YAML drifts from the named constant other tests reference | Pinned by `tests/test_seed_capability_parity.py`; failure tells you which side moved |
| `executor.yaml::pack_options.host_files.allowed_write_paths` ↔ `jarvis.yaml::READ_HOST_FILE.constraints.allowed_host_paths` | Adapter ceiling and policy allowlist disagree | "Guardian approved, executor refused" inconsistency, and vice versa |
| `passive_read_action_ids` on bundle ↔ policy `safe: true` | Passive-read list out of sync with policy | Read action pays full AE when it should ALLOW deterministically, or vice versa |
| `DENY_WRITE_PREFIXES` ↔ canonicalizer used by that family | Deny list stores canonical form, checker compares raw form (or vice versa) | `/etc/sudoers` blocked but `/private/etc/sudoers` allowed, or similar macOS-only asymmetries |
| Constraint field names across families | Two constraints share a field name | Pydantic Union misroutes payloads to a sibling checker silently |

A good rule: whenever you add or rename a list that enumerates action types, ask "is there another list somewhere that should also be updated?" If yes, add a runtime assertion or a mirror test.

---

## Detecting drift (what to run when something feels off)

- **Count check (fastest).** In a terminal:
  ```bash
  python -c "from intentframe_gateway import bootstrap; print(len(bootstrap.SAFE_ACTIONS)+len(bootstrap.UNSAFE_ACTIONS))"
  ```
  Compare to "Allowed Actions: N" in the handshake banner. They must match.

- **Mirror check.** `bootstrap.py` and `seed_policies.py` now both
  load through the same `policy_registry.seeds.load_policy_seed`, so
  the historical drift between them cannot occur.  What can still
  drift is the YAML vs the named capability constant — pinned by
  `tests/test_seed_capability_parity.py`.  Run it directly when in
  doubt:
  ```bash
  python -m pytest tests/test_seed_capability_parity.py -v
  ```

- **Agent advertisement vs tool surface.** Compare `_ACTION_TYPES` in `jarvis_pa/jarvis/agent.py` to the `function_tool` wrappers in `jarvis_pa/jarvis/tools.py`. Any tool whose underlying action is not in `_ACTION_TYPES` will be invisible to onboarding.

- **Onboarding prompt check.** Start the gateway, open the handshake banner, and search the printed guardrails for keywords unique to the family (e.g. `~/Documents`, `HOST_FILE`, `DELETE_`). Absence means the onboarding prompt never learned about the family.

- **Live negative test.** Deliberately send the family's most dangerous action to a path that should be denied (`~/.ssh/id_rsa`, `/etc/sudoers`). If it succeeds, the deterministic floor or the checker is missing a wiring.

---

## Symptom → place to look

When you see one of these, jump straight to the file named.

| Symptom | Likely cause | File to inspect |
|---|---|---|
| Handshake action count is lower than you expected | `bootstrap.py` missing new actions | `intentframe_gateway/bootstrap.py` |
| Onboarding prompt has no guidance for a new family | `_ACTION_TYPES` stale, or `onboarding_guardrails()` not implemented | `jarvis_pa/jarvis/agent.py`, `intentframe_native_bundles/actions/<family>/onboarding_guardrails.py` |
| Agent tool call returns "action not allowed by policy" | Policy seeded without that action | `intentframe_gateway/bootstrap.py::_build_default_policy` |
| Guardian approves but executor refuses | Policy allowlist wider than executor ceiling | `executor.yaml` vs policy constraint |
| Pydantic `ValidationError` about `allowed_paths` vs `allowed_host_paths` | Field name mismatch → wrong constraint type picked | `intentframe_native_bundles/actions/*/constraints.py` |
| Write action missing AE system prompt / external context | `build_ai_context()` not implemented or wrong bundle | `intentframe_native_bundles/actions/<family>/bundle.py` |
| Read action ran full AE when policy marks it safe | Missing from `passive_read_action_ids` | Same bundle class |
| RUN_COMMAND catastrophic not blocked pre-AE | `prepare_evidence()` not running shield | `actions/terminal/pre_pipeline.py` |
| WRITE_FILE sensitive path not blocked | `structural_gates()` not wired | `actions/files/deterministic.py` |
| `/etc/foo` blocked but `/private/etc/foo` allowed (macOS) | Canonicalizer / DENY list asymmetry | `resource_registry/floor.py` + relevant checker |
| Mirror test green but runtime broken | Test pinning the wrong file | `tests/test_jarvis_host_scope_mirror.py` |
| LLM keeps picking `RUN_COMMAND` over the structured tool | Tool docstring not discouraging shell alternatives | `jarvis_pa/jarvis/tools.py` |

---

## What the LLM sees vs what runtime enforces

Two disjoint sets. Keep them mentally separate when debugging.

- **LLM sees:** tool docstrings in `jarvis_pa/jarvis/tools.py`, the onboarding guardrails assembled by `render_onboarding_bundle_context` (bundle `onboarding_guardrails()` + manifest sections) via `intentframe_components/onboarding/instructions.py`, the system prompt, per-intent user messages, and whatever the `reason` field last said.
- **Runtime enforces:** `ActionType` enum membership, policy allowed actions (`bootstrap.py`), constraint checkers, deterministic gates, `DENY_WRITE_PREFIXES`, executor adapter floor, sandbox write scope.

Drift between these two produces the most confusing bugs because code looks right but behaviour doesn't match. When something surprises you, ask: "is this a declaration problem (LLM visibility) or an enforcement problem (runtime gate)?" and walk the appropriate column above.

---

## When to extend this doc

Add an entry here whenever:

- You discover a new drift pair between two files in different layers.
- You add a new layer (new gate, new checker, new prompt lane) that other action families will need to register with.
- A bug shipped because a list existed twice and fell out of sync.

The goal is for this doc to become the one place where the cross-cutting fan-out lives, so the next engineer (or future you) can walk a single checklist instead of re-discovering the layers by grep.

---

## Related documents

- [\_internal\_/substrate-plugin-refactor.md](../_internal_/substrate-plugin-refactor.md) — why and how the bundle SDK refactor was done; gate parity with legacy.
- `TODO/shell-mode-host-file-tools-for-jarvis.md` — concrete walkthrough of a real action-family rollout (HOST_FILE).
- `docs/vfs-vs-host-tools.md` — when to use VFS vs host file tools, and
  why a real product profile should usually expose only one family to a
  given LLM.
- `executor/plan.md` — executor architecture + adapter pattern + security invariants.
- `docs/executor-root-mode.md` — how root relates to the containment story (unrelated to wiring, but useful context).
