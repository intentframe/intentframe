# Deterministic enforcement map (legacy branch)

**Branch state:** pre-`intentframe_action_bundle` — terminal logic still inline in `intentframe_server/pipeline.py`.  
**Purpose:** debug where deterministic policy enforcement lives, which actions get special layers, and why policy is coupled to implementation enums rather than action-agnostic manifests.

**No mermaid** — text diagrams only. Line references are approximate anchors in current code.

---

## 1. Executive summary — the scattering problem

Deterministic enforcement is **not one layer**. It is the same conceptual job split across **six process areas**, with **action-id literals** and **constraint-type registries** wired in Python:

```
  intentframe_native_kit/action_registry/types.py     ActionType enum, ACTION_CATEGORIES, ACTION_DOMAINS
  policy_registry/             YAML → UserPolicy.allowed_actions[action_string]
  intentframe_server/          Pre-AE forks: RUN_COMMAND, WRITE_*, email enrich
  command_shield/              Structural command/code analysis (package)
  intentframe_components/      DG, AE fast-paths, checkers, prompt routing
  executor/ + resource_registry/  I/O-time floors (post-approval)
```

**Core tension you observed is correct:**

- Policy is stored as **per-action strings** (`allowed_actions["RUN_COMMAND"]`) with optional **constraint models** (`TerminalConstraints`, `MessageConstraints`, …).
- Runtime enforcement **does not** discover rules from policy alone. It also consults **hardcoded sets** in components (`_PASSIVE_READ_ACTIONS`, `CRITICAL_ACTIONS`) and **hardcoded `if action == …` gates** in pipeline and DG.
- Adding a new action to `intentframe_native_kit.action_registry` does **not** automatically get correct deterministic behavior — someone must update the right set/checker/fork.

---

## 2. End-to-end mind map (one intent, all stations)

```
                         AGENT submits IntentFrame
                                    |
                                    v
+------------------------------------------------------------------+
| ACTOR (intentframe_actor)                                        |
|   - Validates action is known ActionType enum                    |
|   - Optional domain payload schema (ACTION_DOMAINS + DOMAIN_...) |
|   - HTTP POST → intentframe_server                               |
+------------------------------------------------------------------+
                                    |
                                    v
+------------------------------------------------------------------+
| PIPELINE (intentframe_server/pipeline.py)                        |
|                                                                  |
|   [0] Resolve policy (policy_registry client)                    |
|       user_context.allowed_actions keyed by action.value STRING  |
|                                                                  |
|   [L2] PRE-AE — ACTION-SPECIFIC FORKS ONLY HERE:                   |
|        RUN_COMMAND  → command_shield.inspect_command             |
|                     → CATASTROPHIC? early return BLOCK           |
|                     → else CommandIntel + terminal_signals       |
|        WRITE_FILE / WRITE_HOST_FILE → build_file_intel           |
|        (email message actions) → EmailActionBundle.enrich()      |
|                                                                  |
|   [DG] DeterministicGuardian.decide (pre-AE)                     |
|        permission → constraint checker → domain module           |
|        → WRITE_FILE sensitive path BLOCK                         |
|        → WRITE_HOST_FILE / DELETE_HOST_FILE floor BLOCK          |
|        → passive-read ALLOW?  RUN_COMMAND read-only ALLOW?       |
|        → else UNDECIDED                                          |
|                                                                  |
|   if DG == BLOCK  ──────────────────────────────> RETURN       |
|   if DG == ALLOW  ──────────────────────────────> EXECUTOR       |
|                     (skip AE + AI Guardian)                      |
|                                                                  |
|   if DG == UNDECIDED:                                            |
|        [AE] AnalysisEngine.analyze                               |
|             safe + passive set? → deterministic report (no LLM)|
|             RUN_COMMAND catastrophic patterns? → det report      |
|             else LLM (prompt id from strategy / critical sets)   |
|        [G]  AIGuardian.validate                                  |
|             REPEAT: permission, constraints, domain              |
|             safe + no risk flags? → fast ALLOW                   |
|             else LLM Guardian                                    |
|                                                                  |
|   if ALLOW → EXECUTOR                                            |
+------------------------------------------------------------------+
                                    |
                                    v
+------------------------------------------------------------------+
| EXECUTOR (separate process)                                      |
|   - Adapter dispatch by action type                              |
|   - command_shield.quick_check (terminal adapter)                |
|   - resource_registry floor / VFS deny-write prefixes            |
|   - Seatbelt / sandbox templates                                 |
+------------------------------------------------------------------+
```

**Takeaway:** “Deterministic” can short-circuit at **pipeline L2**, **DG**, **AE fast-path**, **Guardian fast-path**, or only at **executor** — depending on action and policy flags.

---

## 3. Layer stack (defense-in-depth — documented in DG header)

From `intentframe_components/guardian/deterministic.py` module docstring:

```
  L0  command_shield (pipeline for RUN_COMMAND; executor quick_check)
  L1  policy_registry patterns (via TerminalConstraints etc. in policy YAML)
  L2  analysis_engine fast-paths (passive read, catastrophic command)
  L3a DeterministicGuardian (this file) — pre-AE
  L3b AIGuardian — repeats 1–2.5 then AI or safe fast-path
  L4  executor adapter + VFS floor + sandbox
```

Same intent can be checked **multiple times** at different layers (by design — redundancy; also complexity).

---

## 4. Policy model — why it is not action-agnostic today

### 4.1 Policy shape

```
UserPolicy
  allowed_actions: dict[ action_id_string , ActionPermission ]
      ActionPermission
          safe: bool          # enables fast-paths when combined with code sets
          constraints: FileConstraints | TerminalConstraints | ... | None
  domain_constraints: finance | deletion | ...
  intent_limits: semantic rules for AI Guardian
```

**Policy is keyed by action id string** (e.g. `"SEND_MESSAGE"`, `"RUN_COMMAND"`).  
If the action is **missing** from `allowed_actions` → BLOCK at permission gate (DG step 1 and again in AIGuardian step 1).

### 4.2 Policy constraint types ↔ implementation checkers (coupling)

Policy declares a **constraint model type**. Runtime maps type → **Python checker class**:

```
  policy_registry.constraints.*     intentframe_components.guardian.checkers.*
  ------------------------------     --------------------------------------------
  FileConstraints          -->       FileChecker
  HostFileConstraints      -->       HostFileChecker
  TerminalConstraints      -->       TerminalChecker  (needs CommandIntel from L2)
  EmailConstraints         -->       EmailChecker
  MessageConstraints       -->       MessageChecker
  BrowserConstraints       -->       BrowserChecker
  ApiConstraints           -->       ApiChecker
  CalendarConstraints      -->       (NO CHECKER REGISTERED — see gap below)
```

Registry: `CONSTRAINT_CHECKERS` in `guardian/checkers/__init__.py`.

**Gap:** `CalendarConstraints` exists in `policy_registry` but is **not** in `CONSTRAINT_CHECKERS`. Calendar actions with calendar constraints in YAML may not get deterministic path enforcement from a checker (only permission + AI).

### 4.3 Code-owned taxonomies (not in policy YAML)

These sets live in **components source** — policy cannot express them today:

```
  analysis/engine.py::_PASSIVE_READ_ACTIONS     (22 action strings)
  routing/criticality.py::CRITICAL_ACTIONS       (11 action strings)
  prompt/strategy.py                             branches on above + RUN_COMMAND caps
  pipeline.py / deterministic.py               explicit ActionType.RUN_COMMAND etc.
```

**Policy `safe: true`** only matters when the action is also listed in `_PASSIVE_READ_ACTIONS` (for DG/AE passive fast-path) or passes Guardian safe+risk check.

---

## 5. Deterministic gate inventory (by module)

| Gate ID | Module | Trigger | Outcome | Action-specific? |
|---------|--------|---------|---------|----------------|
| `command_shield_catastrophic` | `intentframe_server/pipeline.py` L501–535 | `RUN_COMMAND` + command present | BLOCK, never reaches DG | **Yes — RUN_COMMAND only** |
| `command_intel_build` | pipeline L543–563 | same | Evidence for downstream | **Yes — RUN_COMMAND** |
| `file_intel_build` | pipeline + `file_intel.py` | `WRITE_FILE`, `WRITE_HOST_FILE` + string content | Evidence | **Yes — write family** |
| `email_enrich` | `intentframe_native_kit/intentframe_native_bundles/actions/email/bundle.py` | 7 email message actions | Mutates intent target/data via bundle `enrich()` | **Yes — email set** |
| `permission` | `deterministic.py` L197–203 | action not in `allowed_actions` | BLOCK | **Generic** (per-action key) |
| `constraint` | DG L207–220 | `permission.constraints` type | BLOCK | **Generic dispatch**, family checker |
| `domain` | DG L222–236 | `ACTION_DOMAINS[intent.action]` | BLOCK | **Per-action map** in intentframe_native_kit.action_registry |
| `write_file_sensitive_path` | DG L250–259 | `WRITE_FILE` + path heuristic | BLOCK | **Yes — WRITE_FILE** |
| `write_host_file_floor` | DG L275–286 | `WRITE_HOST_FILE` | BLOCK | **Yes** |
| `delete_host_file_floor` | DG L288–299 | `DELETE_HOST_FILE` | BLOCK | **Yes** |
| `passive_read` | DG L306–311 | action in `_PASSIVE_READ_ACTIONS` + `safe` | ALLOW, skip AI | **Set of 22 actions** |
| `run_command_read_only` | DG L314–321 | `RUN_COMMAND` + CommandIntel + caps | ALLOW, skip AI | **Yes — RUN_COMMAND** |
| `ae_passive_fast` | `analysis/engine.py` L294–335 | safe + passive set | Deterministic report | **Set** (duplicate semantics with DG) |
| `ae_catastrophic_cmd` | AE L339+ | `RUN_COMMAND` + pattern match | CRITICAL report | **Yes — RUN_COMMAND** |
| `guardian_permission` | `guardian/engine.py` L287–296 | same as DG | BLOCK | **Generic** (repeat) |
| `guardian_constraint` | G L300–315 | same | BLOCK | **Generic** (repeat) |
| `guardian_domain` | G L317–335 | same | BLOCK | **Generic** (repeat) |
| `guardian_safe_fast` | G L337–347 | `safe` + no risk flags in analysis | ALLOW | **Generic** |
| `executor_floor` | executor VFS / host_files | mutating paths | BLOCK at I/O | **Generic floor**, all writes |
| `executor_quick_check` | terminal adapter | RUN_COMMAND execute | BLOCK | **Yes — terminal** |

---

## 6. Action taxonomy (how the runtime classifies behavior)

```
                    ALL ActionType values (~80+ in registry)
                                    |
        +---------------------------+---------------------------+
        |                           |                           |
   TIER P                      TIER S                      TIER G
   Passive read set            Special pre-pipeline          Generic
   (22 actions)                forks in pipeline.py          (everything else)
        |                           |                           |
        |                    +------+------+                    |
        |                    |      |      |                    |
        |                 RUN_CMD  WRITE*  EMAIL*                |
        |                    |      |      |                    |
        v                    v      v      v                    v
   DG passive_read      shield  file_intel enrich          permission only
   ALLOW if safe=true    intel   (optional) (optional)      + constraints IF
   SKIP AE+Guardian      |      |      |                    policy assigns
        |                |      |      |                    type with checker
        |                +------+------+                    |
        |                       |                           |
        +-----------+-----------+                           |
                    |                                       |
              TIER C (11 actions)                           |
              CRITICAL_ACTIONS set                          |
              → AE critical_* prompts                       |
              → Guardian critical prompt                    |
                    |                                       |
                    +------------------+--------------------+
                                       |
                              TIER W write lane
                              WRITE_FILE/HOST in strategy
                              (not in CRITICAL_ACTIONS set)
```

**Tier P — passive read (deterministic ALLOW, no LLM):**  
`READ_FILE`, `LIST_DIRECTORY`, `READ_HOST_FILE`, `LIST_HOST_DIRECTORY`, calendar/reminder/contact/notes **reads**, `READ_MESSAGES`, email **reads**, `GET_CLIPBOARD`, `SEARCH_SPOTLIGHT`, system **getters** — see `analysis/engine.py` L183–220.

**Tier S — special pre-AE (pipeline only):**  
`RUN_COMMAND`, `WRITE_FILE`, `WRITE_HOST_FILE`, email enrich actions.

**Tier C — critical AI lane (still deterministic *routing*, LLM for judgment):**  
`RUN_COMMAND`, `PAY_INVOICE`, all `DELETE_*` listed, `SEND_EMAIL`, `HTTP_POST` — `routing/criticality.py`.

**Tier G — generic:**  
Example: `SEND_MESSAGE`, `CREATE_EVENT`, `UPDATE_CONTACT`, `SET_VOLUME`, … — no pipeline fork, not in passive set, not in critical set (unless added later).

---

## 7. Case study diagrams

### 7.1 `RUN_COMMAND` (e.g. `date`, `hostname`) — maximum deterministic surface

```
  intent.action = RUN_COMMAND
        |
        v
  [pipeline L2] command_shield.inspect_command
        |-- CATASTROPHIC --> BLOCK (stop)
        |
        +-- SAFE/NEEDS_REVIEW --> CommandIntel + signals
        |
        v
  [DG]
        |-- permission (TerminalConstraints in policy?)
        |       TerminalChecker uses CommandIntel capabilities
        |-- domain: none (RUN_COMMAND not in ACTION_DOMAINS)
        |-- write gates: skip
        |-- passive_read: no (not in set)
        |-- read_only ALLOW? --> if caps match read_only:* only
        |       YES --> ALLOW, skip AE+Guardian --> executor
        |       NO  --> UNDECIDED
        v
  [AE] (only if UNDECIDED)
        |-- catastrophic pattern in command string? --> det report
        |-- else LLM critical_run_command / network_* lane
        v
  [Guardian]
        |-- repeat permission/constraints/domain
        |-- critical prompt (RUN_COMMAND in CRITICAL_ACTIONS)
        v
  [executor terminal adapter]
        command_shield.quick_check again
        sandbox + run
```

**Scattered terminal logic today:** pipeline L2, DG L314–321, TerminalChecker, AE catastrophic + prompt strategy, executor quick_check.

---

### 7.2 `SEND_MESSAGE` — “send message today” (typical generic mutator)

Assumptions: action allowed in policy with `MessageConstraints`; **not** `safe: true` for passive path; not in `CRITICAL_ACTIONS`.

```
  intent.action = SEND_MESSAGE
        |
        v
  [pipeline L2]
        |-- command_shield: SKIP (not RUN_COMMAND)
        |-- file_intel: SKIP
        |-- email enrich: SKIP (not in email set)
        |
        v
  [DG]
        |-- permission: must have SEND_MESSAGE in allowed_actions
        |-- constraint: MessageChecker (contact allowlist) IF MessageConstraints in policy
        |-- domain: none (SEND_MESSAGE not in ACTION_DOMAINS)
        |-- write/host special gates: SKIP
        |-- passive_read: SKIP (not in 22-set)
        |-- run_command_read_only: SKIP
        |--> UNDECIDED
        |
        v
  [AE] full LLM, prompt_id = standard
        (not critical, not write_file, not run_command)
        |
        v
  [Guardian] full LLM, prompt_id = standard
        (SEND_MESSAGE not in CRITICAL_ACTIONS)
        |
        v
  [executor messages adapter]  (if ALLOW)
```

**No special deterministic code** for SEND_MESSAGE beyond **generic permission + MessageChecker** — exactly the “goes to full AI pipeline” case you described.

---

### 7.3 `LIST_CALENDARS` — passive read fast path

Policy: `LIST_CALENDARS` in `allowed_actions` with `safe: true`.

```
  [pipeline L2]  all SKIP
  [DG]
        permission OK
        constraints: only if CalendarConstraints attached
                     (no CalendarChecker — likely no op at checker stage)
        passive_read ALLOW  --> matched_gate=passive_read
  STOP (no AE, no AI Guardian)
  [executor]
```

**Deterministic ALLOW without LLM** — but eligibility is defined in **code set**, not policy alone (`safe` + membership in `_PASSIVE_READ_ACTIONS`).

---

### 7.4 `CREATE_EVENT` — generic mutator with weak deterministic coverage

```
  [pipeline L2]  SKIP
  [DG]
        permission
        constraints: CalendarConstraints possible in YAML — NO checker registered
        no action-specific DG gates
        --> UNDECIDED
  [AE]  standard LLM
  [Guardian] standard LLM (CREATE_EVENT not critical)
  [executor calendar adapter]
```

Calendar policy fields may exist in YAML but **deterministic checker path is incomplete** vs File/Terminal/Email families.

---

### 7.5 `SEND_EMAIL` — critical lane + email checker

```
  [pipeline L2]  email enrich SKIP (SEND uses data.to, not message-id enrich set)
  [DG]
        permission
        EmailChecker on recipients
        not passive, not write-floor
        --> UNDECIDED (typical)
  [AE]  critical_generic or standard variant
  [Guardian]  critical prompt (in CRITICAL_ACTIONS)
```

---

### 7.6 `ASK_USER` / `SHOW_MESSAGE` — user-IO (forced AI inspection)

Explicitly **excluded** from `_PASSIVE_READ_ACTIONS` (comments in AE + DG).  
Always **UNDECIDED** at DG → AE inspects prompt content → Guardian rubric for questions not commits.

```
  [pipeline L2]  SKIP
  [DG]  never passive_read ALLOW
  [AE]  always LLM (no passive fast-path)
  [Guardian]  standard unless marked critical (not in CRITICAL set)
```

---

## 8. UNDECIDED vs ALLOW vs BLOCK — decision flow (compressed)

```
                    start
                      |
                      v
              allowed_actions?
                 /        \
               no          yes
              BLOCK         |
                            v
                   pipeline L2 early?
                      /         \
                   BLOCK          continue
                            |
                            v
                      DG.decide
                    /    |     \
                BLOCK  ALLOW  UNDECIDED
                  |      |        |
                  |      |        +---> AE (fast or LLM)
                  |      |                |
                  |      |                v
                  |      |            Guardian
                  |      |           /        \
                  |      |        BLOCK      ALLOW
                  |      |          |          |
                  v      v          v          v
                RETURN  RETURN    RETURN     executor
                (fail)  (ok,     (fail)     (+floors)
                        no LLM)
```

---

## 8.1 Exception policy (bundle refactor — post-`66e567c`)

**Question:** When a bundle hook or checker raises, should DG fall through to AE + AI Guardian?

**Answer: No — BLOCK fail-closed.** Do not re-litigate this as “helpful UX.”

```
  bundle phase raises
        |
        v
  DG.decide_async except handler
        |
        v
  BLOCK  matched_gate="exception"
         dg_exception=<repr> on audit
         decision_path="deterministic"
        |
        v
  pipeline stops (no AE, no Guardian, no executor)
```

### Why not UNDECIDED → AI (legacy `66e567c` behavior)?

| Concern | BLOCK | UNDECIDED → AI |
|---------|-------|----------------|
| Constraint YAML may not have run | Safe — no execution | Policy bypass risk |
| `command_intel` / `file_intel` may be missing | Safe | AE runs on weaker context |
| Audit meaning | Clear infra failure | Looks like normal AI review |
| Substrate contract | Host failed → refuse | Host failed → ask LLM |

An exception means **deterministic machinery broke its contract**, not “semantic ambiguity.”
UNDECIDED is reserved for phases that **completed** and found no short-circuit.

### Implementation anchors

- `intentframe_components/guardian/deterministic.py` — `decide_async` except → `DeterministicDecision.BLOCK`
- `intentframe_server/pipeline.py` — BLOCK audit includes `dg_exception` when set
- Tests: `TestFailClosedExceptionHandling`, `TestDgExceptionFailClosed`, `test_bundle_constraint_registry`

### Dev-only escape hatch (not shipped)

A staging flag to revert to UNDECIDED for debugging is acceptable **only** if explicitly env-gated
and never enabled for root/production profiles. Default remains BLOCK.

---

## 8.2 Missing constraint checker (constraint defined, not wired)

**Example:** `LIST_CALENDARS` + `CalendarConstraints` in YAML — no calendar bundle, no
`CONSTRAINT_CHECKERS[CalendarConstraints]`.

**Short answer:** Does **not** BLOCK deterministically; does **not** skip straight to executor.
Falls through to **AE + AI Guardian**; executor only if AI path → ALLOW.

```
1. Permission          → pass
2. Bundle lookup       → NullActionBundle (no calendar bundle)
3. prepare_evidence    → no-op
4. enrich              → no-op
5. check_policy        → CONSTRAINT_CHECKERS.get(CalendarConstraints) → None
                         → continue (no BLOCK)
                         → constraint_checker_skipped on BundleContext + log warning
6. domain              → skip (not a domain action)
7. structural / allow  → passive ALLOW if safe=True, else no-op
8. DG                  → ALLOW or UNDECIDED

9. Analysis Engine     → skipped on DG ALLOW; else runs
10. AI Guardian        → _check_constraints: no checker → continue + same audit field
11. Executor           → only if Guardian → ALLOW
```

Enforcement for unmapped types is **not** deterministic — Guardian may expose raw constraint
JSON in the prompt (`str(constraints)` when `summarize()` is unavailable). That is LLM context,
not a gate.

**Runtime signals (post-refactor):**

- `logging.warning` from `intentframe_bundle_sdk.constraint_checker_skip`
- `verbose=True` → pipeline prints `⚠ constraint checker skipped: …`
- Audit: `constraint_checker_skipped: "CalendarConstraints"` on `audit_entry`

**CI:** `tests/test_bundle_constraint_registry.py` fails if a *new* constraint type is unmapped;
`CalendarConstraints` is explicitly allowlisted until a checker ships.

**Anchors:** `ActionBundle.check_policy`, `AIGuardian._check_constraints`,
`BundleContext.constraint_checker_skipped`, `enrichment_audit_fields()`.

---

## 9. Duplication map (same check, multiple places)

```
  CHECK                    | DG pre-AE | AE      | AIGuardian | Executor
  -------------------------|-----------|---------|------------|----------
  permission deny-default  |     X     |    -    |     X      |    -
  constraint by type     |     X     |    -    |     X      |    -
  domain finance/deletion|     X     |    -    |     X      |    -
  passive read ALLOW     |     X     |  X*     |  (via safe)|    -
  RUN_COMMAND read-only    |     X     |    -    |     -      |    -
  command_shield catastrophic | X (L2) |  X**   |     -      |  X***
  WRITE sensitive path   |     X     |    -    |     -      |  X****
```

`*` AE passive only if DG did not already ALLOW (DG ALLOW skips AE).  
`**` AE catastrophic patterns for RUN_COMMAND on UNDECIDED path.  
`***` executor `quick_check` on execute.  
`****` VFS/host floor on write/delete paths.

---

## 10. Policy enforcement vs implementation — coupling diagram

```
  INTENTFRAME IMPLEMENTATION                          USER POLICY YAML
  ==========================                          ================

  ActionType enum  ──────────────── maps to ────────> allowed_actions keys
       |                                                    |
       +-- ACTION_CATEGORIES (FILE, TERMINAL, ...)            |
       |         |                                            |
       |         v                                            v
       |    CONSTRAINT_CHECKERS[type]  <─────── permission.constraints
       |                                                    |
       +-- ACTION_DOMAINS (deletion, finance)  <── domain_constraints
       |                                                    |
       +-- _PASSIVE_READ_ACTIONS (hardcoded)  <── safe:true (partial)
       |     NOT derivable from policy alone                 |
       |                                                    |
       +-- CRITICAL_ACTIONS (hardcoded)  <── NOT in policy   |
       |                                                    |
       +-- pipeline if action==RUN_COMMAND  <── NOT in policy |
       +-- pipeline if action in WRITE_*     <── NOT in policy |
       +-- enrich_email action set           <── NOT in policy |
```

**What action-agnostic policy would look like (target, not current):**

```
  manifest[action_id].deterministic_gates = [...]
  manifest[action_id].evidence_providers = [...]
  manifest[action_id].ae_lane = passive | critical | standard
  policy only supplies limits (paths, recipients, caps) — not action identity
```

---

## 11. Where complexity concentrates (heatmap)

```
  Module                          | Generic | Action literals | Sets/frozensets
  --------------------------------|---------|-----------------|------------------
  intentframe_server/pipeline.py  |    *    |       ***       |       *
  guardian/deterministic.py       |   **    |       ***       |      **
  analysis/engine.py              |    *    |       **        |      **
  prompt/strategy.py              |    *    |       ***       |      **
  routing/criticality.py          |    -    |       ***       |      ***
  guardian/checkers/*             |   **    |        *        |       *
  intentframe_native_kit/intentframe_native_bundles/actions/email/bundle.py |    -    |       ***       |      **
  file_intel.py                   |    -    |       **        |       *
  command_shield                  | family  |     RUN_COMMAND |       -
  executor adapters               |  floor  |     per-action  |       -
  policy_registry/models        | action key|  constraint type|       -
```

Legend: `*` = some generic machinery; `***` = heavy action-specific coupling.

---

## 12. Quick reference — “does this action have special deterministic code?”

| Action example | Pipeline L2 fork | DG special gate | Passive set | Critical set | Typical path |
|----------------|------------------|-----------------|-------------|--------------|--------------|
| `RUN_COMMAND` | shield + intel | read-only ALLOW | no | yes | DG ALLOW or critical AI |
| `WRITE_FILE` | file intel | sensitive path BLOCK | no | no (write lane) | UNDECIDED → critical_write_file AE |
| `WRITE_HOST_FILE` | file intel | host floor BLOCK | no | no | UNDECIDED → critical_write_file AE |
| `DELETE_HOST_FILE` | — | delete floor BLOCK | no | yes | UNDECIDED → critical AI |
| `SEND_MESSAGE` | — | — | no | no | full standard AI |
| `LIST_CALENDARS` | — | — | yes | no | DG ALLOW if safe |
| `GET_EMAIL` | enrich | — | yes | no | DG ALLOW if safe |
| `REPLY_EMAIL` | enrich | — | no | no | UNDECIDED + EmailChecker |
| `SEND_EMAIL` | — | — | no | yes | critical AI |
| `CREATE_EVENT` | — | — | no | no | full standard AI |
| `HTTP_POST` | — | — | no | yes | critical AI |
| `ASK_USER` | — | — | no (excluded) | no | forced AI (prompt safety) |
| `PAY_INVOICE` | — | finance domain | no | yes | domain BLOCK or critical AI |

---

## 13. Files to open when debugging a single intent

```
  1. jarvis_pa/.../policies/*.yaml OR ~/.intentframe/policies/<agent>.yaml
  2. intentframe_server/pipeline.py  (_process_intent_impl)
  3. intentframe_components/guardian/deterministic.py
  4. intentframe_components/analysis/engine.py  (if UNDECIDED)
  5. intentframe_components/prompt/strategy.py + routing/criticality.py
  6. intentframe_components/guardian/engine.py
  7. intentframe_native_kit.action_registry/types.py  (category, domain for action)
  8. executor/platforms/.../adapters/<family>.py  (if executed)
```

---

## 14. Relation to bundle refactor direction

This map describes **legacy** scattering. The intended consolidation (your mental model):

```
  per-action bundle:
    enrich()
    deterministic()   # all gates + evidence in one ordered stack
    evidence → AE / Guardian
  substrate:
    permission + shared floors + audit only
```

Until bundles own `deterministic()`, moving pipeline blocks alone only relocates **L2** fragments — DG/AE/Guardian/executor deterministic pieces listed above remain separate.

**Post-refactor (current):** `DeterministicRunner` in `intentframe_bundle_sdk` owns gate order; bundle hooks replace inline DG steps. Exception policy is §8.1 (BLOCK, not AI fallback).

---

*Generated from codebase scan on legacy branch. Re-scan after each extraction PR.*
