# Action Family Wiring Map

Status: **developer runbook**. Use this when adding, auditing, or debugging a family of actions (e.g. `FILE`, `HOST_FILE`, `TERMINAL`, `EMAIL`).

This document exists because the IntentFrame pipeline legitimately has many layers (policy, deterministic guardian, analysis engine, AI guardian, executor, onboarding, agent handshake), and a single new action fans out to ~15 files. Most of those files do not reference each other, so drift is silent: code builds green, tests pass, and the only symptom is that something quietly does not reach production at runtime — e.g. the agent advertises a tool the policy does not grant, or the onboarding prompt never mentions a capability the agent actually has.

Read this before adding a new action family. Read it again when you are debugging "why isn't X being enforced / mentioned / routed the way I expect?".

---

## Mental model in one paragraph

An agent submits an intent. It travels through several gates. Each gate is independent, each has its own opinion, and any of them can block. If the intent survives, the executor adapter performs the real I/O. Onboarding, handshake, and tool descriptions are the things the LLM sees; everything else is runtime enforcement the LLM never sees directly. The trick is that the LLM's picture of the world is built from **declarations** (tool docstrings, `AgentCapabilities.action_types`, onboarding guardrails), while enforcement is built from **different declarations** (`ActionType` enum, `SAFE_ACTIONS`/`UNSAFE_ACTIONS` policy seed, checker registry, critical-action sets). When those two sets of declarations drift, the agent sees capabilities the runtime blocks (or vice versa).

---

## The two vocabularies

Before touching anything file-path-related, be explicit about which world you are in:

| Vocabulary | Example | Canonicalizer | Checker | Constraint type |
|---|---|---|---|---|
| Virtual filesystem | `/home/foo.txt` | `normalize_virtual_path` | `FileChecker` | `FileConstraints.allowed_paths` |
| Host filesystem | `~/Documents/foo.txt` | `canonicalize_real_path` | `HostFileChecker` | `HostFileConstraints.allowed_host_paths` |

The two must **never** share a constraint field name. The disjoint field names (`allowed_paths` vs `allowed_host_paths`) are what drive Pydantic's smart-union dispatch to the correct constraint type. Renaming or unifying them silently reroutes everything through the wrong checker.

Trailing-slash shorthand for host paths (`~/Documents/`) is rejected at config load time. Use `dir/*` for subtree scope, exact paths otherwise.

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

### 3. Policy layer

- `policy_registry/constraints/<family>.py` — a new `*Constraints` Pydantic model with `ConfigDict(extra="forbid")` and a **disjoint** field name from every other constraint type. Add a `field_validator` for any syntactic invariants (like rejecting trailing-slash shorthand).
- `policy_registry/registry.py` (or equivalent) — register the constraint type in the Union so it round-trips through serialization.
- `policy_registry/domains/<domain>.py` — if the action participates in a cross-family domain (e.g. `DELETION`), wire it there.

### 4. Guardian layer

- `intentframe_components/guardian/checkers/<family>.py` — the checker that consumes the constraint and decides allow/deny. Register it in `CONSTRAINT_CHECKERS`.
- `intentframe_components/guardian/deterministic.py` — if there is a deterministic gate (passive-read fast path, write-floor block, delete-floor block), add or extend it here.
- `resource_registry/floor.py` — if this family writes to the host filesystem, extend `DENY_WRITE_PREFIXES` with any non-negotiable deny roots.

### 5. Analysis Engine + prompt strategy

- `intentframe_components/analysis/engine.py::_PASSIVE_READ_ACTIONS` — add read-only actions here so they skip full AE analysis.
- `intentframe_components/routing/criticality.py::CRITICAL_ACTIONS` — add high-risk actions (deletes, privileged writes) so they take the critical AIGuardian lane.
- `intentframe_components/prompt/strategy.py` — route write/delete actions to the right prompt template (`critical_write_file`, `standard`, etc.).
- `intentframe_server/pipeline.py::_build_file_intel` — if the family has a payload (write content), extend the condition that attaches File Shield intel.

### 6. Agent + onboarding (LLM-visible surface)

- `jarvis_pa/jarvis/tools.py` — add `function_tool` wrappers with docstrings that name the vocabulary and discourage mixing with other tools.
- `jarvis_pa/jarvis/agent.py::_ACTION_TYPES` — add the new action types so they appear in `AgentCapabilities` at handshake.
- `intentframe_components/onboarding/engine.py` — if the family needs its own guardrail block in the prompt, add a section here.

### 7. Policy seed (the runtime truth)

- `intentframe_gateway/bootstrap.py` — the **runtime** policy seeder. Add the actions to `SAFE_ACTIONS` / `UNSAFE_ACTIONS`. Wire the new constraint into `_build_default_policy()` with the correct disjoint field name. This is the file the gateway actually runs on startup.
- `jarvis_pa/seed_policies.py` — the manual mirror script. Keep it byte-for-byte equivalent to `bootstrap.py` (see "Drift hotspots" below).

### 8. Tests

- `tests/test_policy_<family>_constraints_roundtrip.py` — prove the Pydantic Union dispatches to your new constraint and not a sibling one.
- `tests/test_<family>_checker.py` — positive and negative cases, including any syntactic validators.
- `tests/test_deterministic_guardian.py` — any new gate (passive read, write floor, delete floor).
- `tests/test_prompt_strategy.py` — prove the new actions route to the expected prompt lane.
- `tests/test_<family>_adapter.py` — executor-side path handling.
- `tests/test_jarvis_host_scope_mirror.py` or equivalent — pin the invariant between `executor.yaml` and `bootstrap.py` for this family if there is one.

---

## Drift hotspots (where silent failure lives)

These are the files that **must** stay in sync but have no compiler-enforced relationship. Every one of these has bitten us at least once.

| Pair | What drifts | Symptom |
|---|---|---|
| `bootstrap.py::SAFE_ACTIONS` ↔ `ActionType` enum | Bootstrap missing new actions | Handshake total count is lower than enum size; agent sees tool, policy denies at runtime |
| `jarvis_pa/jarvis/agent.py::_ACTION_TYPES` ↔ `tools.py::ALL_TOOLS` | Agent advertises fewer actions than it can call | Onboarding prompt has no guardrails for the missing actions; agent still calls them, no policy-side guidance |
| `bootstrap.py` ↔ `jarvis_pa/seed_policies.py` | Manual mirror falls behind runtime | Dev runs `seed_policies.py` expecting parity, gets stale behaviour |
| `executor.yaml::host_files.allowed_write_paths` ↔ `bootstrap.py::host_constraint` | Adapter ceiling and policy allowlist disagree | "Guardian approved, executor refused" inconsistency, and vice versa |
| `_PASSIVE_READ_ACTIONS` ↔ `CRITICAL_ACTIONS` ↔ `prompt/strategy.py` | One says passive, another says critical | Action takes a different lane than its risk warrants; AE or AIGuardian is skipped when it shouldn't be, or runs when it doesn't need to |
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

- **Mirror check.** `bootstrap.py` vs `seed_policies.py`:
  ```bash
  python -c "
  from intentframe_gateway import bootstrap as b
  from jarvis_pa import seed_policies as s
  assert set(b.SAFE_ACTIONS) == set(s.SAFE_ACTIONS)
  assert set(b.UNSAFE_ACTIONS) == set(s.UNSAFE_ACTIONS)
  bp = b._build_default_policy()['allowed_actions']
  sp = s._build_policy()['allowed_actions']
  assert set(bp) == set(sp)
  for k in bp:
      assert bp[k]['constraints'] == sp[k]['constraints'], k
  print('mirror OK')
  "
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
| Onboarding prompt has no guidance for a new family | `_ACTION_TYPES` stale | `jarvis_pa/jarvis/agent.py` |
| Agent tool call returns "action not allowed by policy" | Policy seeded without that action | `intentframe_gateway/bootstrap.py::_build_default_policy` |
| Guardian approves but executor refuses | Policy allowlist wider than executor ceiling | `executor.yaml` vs policy constraint |
| Pydantic `ValidationError` about `allowed_paths` vs `allowed_host_paths` | Field name mismatch → wrong constraint type picked | `policy_registry/constraints/*.py` |
| Write-file action skipped the critical lane | Missing from `critical_write_file` route | `intentframe_components/prompt/strategy.py` |
| Read action ran a full AE call it didn't need | Missing from `_PASSIVE_READ_ACTIONS` | `intentframe_components/analysis/engine.py` |
| Delete action didn't require confirmation | Missing from `CRITICAL_ACTIONS` | `intentframe_components/routing/criticality.py` |
| New write action didn't get File Shield intel | `_build_file_intel` condition too narrow | `intentframe_server/pipeline.py` |
| `/etc/foo` blocked but `/private/etc/foo` allowed (macOS) | Canonicalizer / DENY list asymmetry | `resource_registry/floor.py` + relevant checker |
| Mirror test green but runtime broken | Test pinning the wrong file | `tests/test_jarvis_host_scope_mirror.py` |
| LLM keeps picking `RUN_COMMAND` over the structured tool | Tool docstring not discouraging shell alternatives | `jarvis_pa/jarvis/tools.py` |

---

## What the LLM sees vs what runtime enforces

Two disjoint sets. Keep them mentally separate when debugging.

- **LLM sees:** tool docstrings in `jarvis_pa/jarvis/tools.py`, the onboarding guardrails rendered from `intentframe_components/onboarding/engine.py` using `AgentCapabilities.action_types`, the system prompt, per-intent user messages, and whatever the `reason` field last said.
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

- `TODO/shell-mode-host-file-tools-for-jarvis.md` — concrete walkthrough of a real action-family rollout (HOST_FILE).
- `executor/plan.md` — executor architecture + adapter pattern + security invariants.
- `docs/executor-root-mode.md` — how root relates to the containment story (unrelated to wiring, but useful context).
