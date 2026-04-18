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
- **Next (OSS release):** Specialised routing. Option A (same components, different prompts) as first step. Surgical change in `pipeline.py`.
- **Future:** Option B (separate instances) when critical path needs fine-tuned models or different infrastructure.
