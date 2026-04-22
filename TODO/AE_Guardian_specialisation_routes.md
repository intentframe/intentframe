# AE & Guardian Specialisation Routes

> Route critical actions to specialised AE/Guardian instances — spend analysis budget where the threats are, not spread thin across everything.

---

## The Problem

Today, the same AE and Guardian instance evaluates `LIST_CALENDARS` (passive read, zero risk) and `RUN_COMMAND "python server.py"` (arbitrary code, unbounded risk). The same prompt template, same model, same evaluation logic.

This creates a tension:

**For passive reads:** You want speed. Fast-path. Zero AI calls. The current design handles this well — `_PASSIVE_READ_ACTIONS` cascading fast-path, zero cost.

**For RUN_COMMAND / PAY_INVOICE / DELETE_FILE:** You want depth. The AE needs to read code content, detect capability signals, check write-then-execute chains, understand financial implications. The Guardian needs to validate template integrity, check capability policy, evaluate domain-specific constraints. These are fundamentally different evaluation tasks than "is this calendar read safe?"

Cramming both into one AE prompt and one Guardian prompt means:

1. **The prompt is bloated** — instructions for terminal analysis, finance analysis, deletion analysis, social engineering detection, all in one system prompt. The model has to figure out which subset applies each time.

2. **No specialisation** — the AE can't be tuned for code analysis when it's also handling email evaluation. Different threat models need different reasoning patterns.

3. **The fast-path becomes fragile** — the more critical-path logic you add to the AE (code content signals, capability detection, template integrity), the harder it is to maintain the clean fast-path for passive reads.

4. **Different trust levels need different scrutiny depths** — a `LIST_REMINDERS` doesn't need the AE to analyse code content or check session write history. A `RUN_COMMAND` does. Forcing them through the same pipeline wastes resources on safe actions and under-serves dangerous ones.

---

## What Separate Critical-Path Evaluation Looks Like

```
Intent arrives
    │
    ├── Is this a CRITICAL action type?
    │   (RUN_COMMAND, PAY_INVOICE, DELETE_FILE, SEND_EMAIL with attachments,
    │    HTTP_POST to external URL, any action with domain_constraints)
    │
    ├── NO → Standard Pipeline
    │   ├── Standard AE (fast-path eligible, general-purpose)
    │   ├── Standard Guardian (policy check, fast-path eligible)
    │   └── Executor (typed adapter, no sandbox needed)
    │
    └── YES → Critical Pipeline
        ├── Command Shield / Domain Pre-check (deterministic, always runs)
        ├── Critical AE (specialised prompt, deeper analysis, NOT fast-path eligible)
        │   ├── Code content analysis (for RUN_COMMAND)
        │   ├── Financial impact analysis (for PAY_INVOICE)
        │   ├── Irreversibility assessment (for DELETE_FILE)
        │   └── Capability signal validation (for RUN_COMMAND)
        ├── Critical Guardian (stricter evaluation, domain modules, template integrity)
        └── Executor (with sandbox template for RUN_COMMAND)
```

This isn't two separate systems — it's the same pipeline with **specialised evaluation paths** based on action criticality. The routing is deterministic (action type lookup), not AI-decided.

---

## What This Buys You

| Benefit | Why it matters |
|---------|---------------|
| **Specialised prompts** | The critical AE prompt for RUN_COMMAND can focus entirely on code analysis, capability detection, process escape patterns. No calendar/reminder/contact instructions diluting it. |
| **Different model tiers** | Standard AE can use a fast, cheap model (gpt-4o-mini). Critical AE can use a deeper, more capable model (gpt-4o, or even a fine-tuned security model). Cost only increases for critical actions. |
| **Fast-path stays clean** | Standard pipeline keeps its cascading fast-path untouched. No new code content analysis logic cluttering the passive read path. |
| **Deeper analysis where it matters** | Critical AE can do multi-step reasoning: read session write history, analyse code content, correlate with capability signals, validate template declarations. Standard AE doesn't need any of this. |
| **Different temperature / parameters** | Critical AE can run at temperature=0 with stricter output parsing. Standard AE can be slightly more flexible. |
| **Independent evolution** | You can improve critical-path analysis (new code patterns, new financial checks) without touching the standard path that already works. |

---

## How It Maps to What Already Exists

The seeds of this pattern are already in the codebase:

- **Domain modules** in Guardian (`Domain-Hardening.md`) — finance and deletion domains already have specialised deterministic checkers. A separate Critical Guardian is the natural extension: specialised AI evaluation on top of specialised deterministic checks.

- **Command Shield** is already a separate pre-pipeline gate specifically for RUN_COMMAND. A Critical AE is the AI equivalent — specialised analysis specifically for critical action types.

- **`_PASSIVE_READ_ACTIONS`** already defines which actions DON'T need deep analysis. The inverse of this set is roughly the "critical actions" set.

- **Fast-path gates** already route safe actions differently from risky ones. A separate Critical AE is just making that routing explicit at the component level rather than inside the prompt.

---

## Implementation Options

### Option A: Same Components, Different Prompts

- One `AnalysisEngine` class, but with `critical_prompt` and `standard_prompt`
- Routing logic in the engine selects which prompt based on action type
- Simpler to implement, same codebase

### Option B: Separate Component Instances

- `StandardAnalysisEngine` and `CriticalAnalysisEngine` as separate instances
- Different models, different configs, potentially different infrastructure
- Cleaner separation, independently deployable, different scaling characteristics

**Option A is the pragmatic first step. Option B is where it goes when the critical path needs a fine-tuned model or different infrastructure.**

---

## The Routing: Zero Overhead

The routing is already there — `intent.action` is an enum. It's a dictionary lookup, not an LLM decision. Zero added latency, zero added cost.

In `pipeline.py`, the routing point is already visible — where `self.analysis_engine.analyze()` is called (line ~383) and `self.guardian.validate()` is called (line ~415). Route to different engine instances based on action type before those calls. The pipeline structure doesn't change. The flow doesn't change. Just which engine instance handles it.

---

## Critical Action Classification

Not every action needs the critical path. The classification is deterministic:

| Action | Pipeline | Why |
|--------|----------|-----|
| READ_FILE, LIST_DIRECTORY | Standard | Passive read, VFS-bounded |
| LIST_CALENDARS, LIST_EVENTS, LIST_REMINDERS | Standard | Passive read, TCC-gated |
| SEARCH_CONTACTS, GET_CONTACT, GET_CLIPBOARD | Standard | Passive read |
| SEARCH_SPOTLIGHT, LIST_NOTES | Standard | Passive read |
| CREATE_EVENT, UPDATE_EVENT, CREATE_REMINDER | Standard | Low-risk mutation, typed adapter |
| **RUN_COMMAND** | **Critical** | Arbitrary code execution |
| **PAY_INVOICE** | **Critical** | Financial impact |
| **DELETE_FILE, DELETE_EVENT** | **Critical** | Irreversible data loss |
| **SEND_EMAIL** | **Critical** | External communication, social engineering vector |
| **HTTP_POST** | **Critical** | External network, exfiltration vector |
| **WRITE_FILE** | **Depends** | Standard normally, critical if writing executable code |

The routing is a simple set lookup — same pattern as `_PASSIVE_READ_ACTIONS` but for the opposite end of the spectrum. Deterministic, no AI in the routing decision.

---

## Sub-routing inside the Critical path: the network-probe lane

Within `RUN_COMMAND` (already on the critical path), `command_shield`
now emits a `capability:network_probe:*` family that splits the
critical-path traffic further.  Rather than routing every outbound-
traffic command through the single generic critical AE, the critical
pipeline can apply a second, zero-overhead deterministic routing step
based on the capability tags:

| `network_probe:*` sub-tag | Route |
|---|---|
| `icmp`, `trace`, `dns`, `whois` | **Probe-lane AE** — lightweight critical prompt that knows the command is a local / informational probe. Fast model, short prompt. Deterministic ALLOW if policy permits the specific family against the target (e.g. corp DNS). |
| `http_get` | **Probe-lane AE** + URL/domain allow-list check. Fast-path ALLOW if the URL is on a per-tool allow-list; otherwise the probe-lane prompt evaluates the full context. |
| `http_mutate`, `http_download` | **Network-mutation AE** — stricter critical prompt. Must reason about the target URL, request body, and data-exfiltration risk. Never deterministic ALLOW. |
| `port_scan`, `file_transfer` | **Network-mutation AE** — plus a reminder in the prompt that this pattern is a common exfiltration / lateral-movement shape. Never deterministic ALLOW. |

Why this matters:

- **Prompt specialisation.** The probe-lane prompt can be ~30% the
  size of the generic critical prompt because it knows the command
  shape: no code-content inspection, no write-then-execute reasoning,
  just domain/URL policy.  The network-mutation prompt, conversely,
  leans in on exfiltration heuristics.
- **Model tiering.** Probe lane can use the fast/cheap model; network-
  mutation lane deserves the deeper model.
- **Zero routing cost.** Just like the primary critical/standard
  split, this is a dictionary lookup on `report.capabilities` — no
  extra LLM call to decide routing.
- **Fast-path is still possible for innocuous probes.** A dev laptop
  policy might deterministically ALLOW `network_probe:dns` and
  `network_probe:icmp` without AE at all.  `command_shield` emits the
  tags under the same strict structural gate as `read_only:*`, so
  they're trustworthy for deterministic use.

Implementation is additive on top of Option A: the `AnalysisEngine`
picks one of three prompts (`standard`, `critical_generic`,
`critical_network_probe`, `critical_network_mutation`) based on the
action type plus the capability tags, with everything else unchanged.
Under Option B this becomes two separate engine instances inside the
critical path (`CriticalProbeEngine`, `CriticalMutationEngine`).

---

## Relationship to Prevention-First Philosophy

This fits naturally with the prevention-first model from [Execution-Security-Model.md](../concepts/extras/Execution-Security-Model.md):

- **Passive reads** → fast-pathed (zero AI cost, zero latency)
- **Standard mutations** → general-purpose AE + Guardian (moderate cost)
- **Critical actions** → specialised AE + Guardian (deep analysis, higher cost, maximum prevention)

The pipeline's intelligence is concentrated where the bombs are, not spread thin across everything. Spend analysis budget where the threats are.

---

## Status

- **Current (V1/MVP):** Single AE + single Guardian. Proved the architecture works. Validated by milestones and 24 attack tests.
- **Shipped (commit `e705d57`) — Option A plumbing (prompt specialisation & criticality routing):** See "What shipped" below.
- **Next (OSS release):** Author full-body forks for probe / mutation sub-lanes (`critical_network_probe`, `critical_network_mutation`) based on `_CRITICAL_RUN_COMMAND`.  Update the aliasing assertions in `tests/test_prompt_library.py::TestInitialRolloutAliasing` to reflect the new bodies.
- **Future:** Option B (separate-engine-instances architecture) when the critical path needs fine-tuned models or different infrastructure.

---

## What shipped (prompt specialisation & criticality routing)

Commit `e705d57` ("refactor pipeline prompt strategy and routing") lands
**the full routing plumbing under Option A with the overlay content
intentionally neutralised to the empty string**.  The production LLM sees
byte-identical prompts to the pre-specialisation baseline for every action
type, while every seam needed to later turn on specialised bodies is live
and covered by tests.

### Components added

| Module | Purpose |
|---|---|
| `intentframe_components/routing/criticality.py` | `CRITICAL_ACTIONS` frozenset + `is_critical()` helper — single source of truth for which action types ride the critical lane. |
| `intentframe_components/prompt/library/analysis.py` | AE prompt bodies: `standard`, `critical_generic` (= standard), `critical_run_command` (full fork), `critical_write_file` (full fork), `critical_network_probe` / `critical_network_mutation` (aliased to `critical_run_command`). |
| `intentframe_components/prompt/library/guardian.py` | Guardian prompt bodies: `standard`, `critical` (= standard). No overlay pattern — specialisation uses full-body forks. |
| `intentframe_components/prompt/strategy.py` | `PromptStrategy` Protocol + `DefaultPromptStrategy` — deterministic selection of AE / Guardian prompt ids from `intent.action` and `command_intel.capabilities`. |
| `AIAnalysisEngine`, `AIGuardian` | Now accept `prompt_strategy` at construction, hold one `Agent` per prompt id, and expose `last_prompt_id` for audit. |
| `intentframe_server/pipeline.py` | Records `ae_prompt_id` / `guardian_prompt_id` in the audit entry when the AI path ran; resets the engine-side `last_prompt_id` at the start of every request so deterministic / fast-path outcomes never inherit stale values. |

### Tests added

| File | What it pins |
|---|---|
| `tests/test_prompt_strategy.py` | AE routing matrix (RUN_COMMAND × capability sub-tags, critical non-command actions, non-critical actions), Guardian routing matrix, precedence (mutation > probe > generic), fail-closed when `command_intel` is missing on RUN_COMMAND, drift guard `CRITICAL_ACTIONS ∩ _PASSIVE_READ_ACTIONS == ∅`. |
| `tests/test_prompt_library.py` | Shape (all ids present, non-empty, read-only mapping), standard-body keyword invariants, critical-overlay invariants (6 tests `xfail(strict=False)` as living placeholders for the initial rollout), aliasing of probe / mutation lanes. |
| `tests/test_audit_prompt_id_reset.py` | Regression: deterministic-ALLOW and deterministic-BLOCK audit entries must not carry `ae_prompt_id` / `guardian_prompt_id` from a preceding AI-path request. |

### Routing wired end-to-end

Analysis Engine (precedence — strictest first):

1. `critical_network_mutation` — RUN_COMMAND + any of `capability:network_probe:{http_mutate, http_download, port_scan, file_transfer}`
2. `critical_network_probe` — RUN_COMMAND + any of `capability:network_probe:{icmp, trace, dns, whois, http_get}`
3. `critical_generic` — action ∈ `CRITICAL_ACTIONS` (includes RUN_COMMAND without known sub-tags, and RUN_COMMAND with missing `command_intel` — fail-closed)
4. `standard` — everything else

Guardian:

1. `critical` — action ∈ `CRITICAL_ACTIONS`
2. `standard` — everything else

### What is deliberately deferred

- **Probe / mutation sub-lane specialisation.** `critical_network_probe` and `critical_network_mutation` alias `critical_run_command` in the initial rollout.  Per-lane full-body forks will replace them without any engine / strategy / test change beyond the library file and `tests/test_prompt_library.py::TestInitialRolloutAliasing` (whose docstring says to delete those assertions when the alias ends).  No overlay pattern — new bodies are standalone forks.
- **`critical_generic` and Guardian `critical` bodies.** Both deliberately equal their respective `standard` bodies.  `critical_generic` covers PAY_INVOICE, DELETE_*, SEND_EMAIL, HTTP_POST — typed, structured actions whose rubric is already well-served by the standard body.  Guardian's standard body is already enforcement-heavy.  If deeper specialisation is later justified, author a full-body fork (not an overlay).
- **Model tiering.** Every lane currently uses the same model.  The seams (one `Agent` per id, lane name in `Agent.name`) are ready for per-lane model configuration when wanted.

### Guardrails against regression

- `DefaultPromptStrategy` is pure and sync → trivially testable without spinning up agents.
- Unknown prompt ids fall back to `"standard"` with a warning log, never crash (`_resolve_prompt_id` in both engines).
- `last_prompt_id` is reset at two levels: per-request in `pipeline._process_intent_impl` (covers short-circuits) **and** on every `analyze()` / `validate()` entry (covers the AI path).  Either reset alone would fix the original audit-leak bug; both together make the invariant independent of call-site order.
- The audit fields are only added when `last_prompt_id` is set, so absent fields correctly mean "no AI prompt was used" — they do not ambiguate between "stale" and "clean".
