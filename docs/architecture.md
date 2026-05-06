# IntentFrame Architecture

> No single intelligent entity can simultaneously define, validate, and execute intent.

IntentFrame is a **runtime security control plane for AI-decided actions** — a policy-enforced pipeline that sits between an AI agent and the real world.

The effect of that control plane is that it **automates the oversight a human would otherwise perform manually**: reading every action, understanding what it will really do, applying judgment, and clicking approve or reject. The agent does the work; IntentFrame automates the supervision.

Both framings describe the same system from different angles. The security framing answers *"what is it?"* — a runtime boundary with deterministic gates, semantic review, and executor isolation. The oversight framing answers *"why does it exist?"* — because manual human-in-the-loop review of every AI action does not scale, and giving agents unsupervised access to the real world is not safe.

---

## The Separation Invariant

```
No single entity can: THINK + UNDERSTAND + JUDGE + ACT

Agent:           THINKS      (cannot validate, judge, or act)
Actor:           PARSES      (cannot understand semantics, judge policy, or act)
Analysis Engine: UNDERSTANDS (cannot judge policy or act)
Guardian:        JUDGES      (cannot act)
Executor:        ACTS        (cannot judge)
```

This is the fundamental design constraint. Every other architectural decision flows from it.

---

## The Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: THIRD-PARTY AGENT ("The Thinker")                     │
│  • Developer's AI — any LLM, any framework                      │
│  • Does reasoning, planning, intent formation                   │
│  • UNTRUSTED — output treated as potentially adversarial        │
└─────────────────────┬───────────────────────────────────────────┘
                      │ (unstructured intent)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: ACTOR ("The Parser & Gateway")                        │
│  • Platform-controlled, trusted binary (in SDK)                 │
│  • Parses, authenticates, enriches, forwards                    │
│  • TRUSTED — simple gateway, no intelligence                    │
└─────────────────────┬───────────────────────────────────────────┘
                      │ (structured Intent Frame)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3: ANALYSIS ENGINE ("The Brain")                         │
│  • Semantic AI that understands what actions REALLY do           │
│  • Code/script behavior analysis, outcome prediction            │
│  • Hidden behavior discovery, intent vs action mismatch         │
│  • OUTPUT: Analysis Report (understanding, NOT decisions)       │
└─────────────────────┬───────────────────────────────────────────┘
                      │ (Analysis Report)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 4: GUARDIAN ("The Judge")                                │
│  • Receives Analysis Report, applies user policies              │
│  • Makes ALLOW / BLOCK decisions                                │
│  • Deterministic gates run first; AI only when needed           │
└─────────────────────┬───────────────────────────────────────────┘
                      │ (validated intent — approved)
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 5: EXECUTOR ("The Hands")                                │
│  • ONLY entity with credentials                                 │
│  • Executes only after Guardian approval                        │
│  • Kernel-sandboxes RUN_COMMAND subprocesses (macOS Seatbelt)   │
│  • TRUSTED — can act but cannot judge                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Intent Frame

The Intent Frame is the fundamental primitive — a structured declaration of what an agent wants to do and why. It is a proposal, not an action. It must be validated before execution.

```
┌─────────────────────────────────────────────────────────────────┐
│  INTENT FRAME                                                   │
│                                                                 │
│  "I (agent) want to do X (action) to Y (target)                │
│   because Z (justification), and I expect W (outcome)."         │
│                                                                 │
│  This is a PROPOSAL, not an action.                            │
│  It must be validated before execution.                         │
└─────────────────────────────────────────────────────────────────┘
```

### Field reference (`intentframe_core.types.IntentFrame`)

The shipped `IntentFrame` Pydantic model has the following fields:

| Field | Type | Purpose |
|---|---|---|
| `action` | `ActionType` enum | The typed operation (e.g., `READ_FILE`, `APPEND_ROW`, `RUN_COMMAND`, `PAY_INVOICE`) |
| `target` | `str` | Who or what the action affects (path, recipient, command, URL) |
| `data` | `Optional[Dict[str, Any]]` | Action-specific structured payload (amount, recipient, content) |
| `reason` | `str` | The agent's stated justification — used by AE for reason-vs-data cross-checks |
| `agent_id`, `session_id`, `sequence_id`, `timestamp` | identity | Who submitted the intent, when, and in what order |
| `task_description`, `authorized_by`, `agent_type`, `actor_verified` | context | Bound at handshake; identifies the user policy this intent runs under |
| `signature` | `str` | Actor handshake stamp (`sig_<agent_id>_<seq>`) — currently a session-bound identifier, not a cryptographic signature. See [docs/threat-model.md](threat-model.md) for the full trust model |

`action`, `target`, `data`, and `reason` are the four fields that flow through the entire pipeline (deterministic gates, Analysis Engine, Guardian, Executor). The remainder are pipeline metadata.

For a working code example showing `actor.submit({...})` with these fields, see the README quickstart snippet.

### The human-governance parallel

The parallel to human governance is not accidental:

| Human governance | IntentFrame |
|---|---|
| Person states intent ("I want to buy this property") | Agent submits Intent Frame |
| Expert assesses implications | Analysis Engine evaluates actual effects |
| Authority approves/denies | Guardian: ALLOW / BLOCK |
| Action is executed with credentials | Executor performs with credentials |
| Record is created | Audit logs recorded |

The principle is universal: **accountability requires separation of desire from action, mediated by judgment.** An Intent Frame is the unit of "desire"; the Analysis Engine and Guardian provide the mediating judgment; the Executor is the unit of action.

---

## The Actor SDK: Why Not an MCP Gateway

> **No tool should ever enforce its own authority.**

That single systems principle drives the SDK design. When tools enforce their own rules — `if amount > limit: return BLOCKED` inside each tool function — enforcement is scattered, inconsistent, and tied to specific implementations. Swap the model, add a new tool, change a policy, and you have to find every hardcoded check. Worse, an agent that finds a way to skip a tool's own check is past the boundary.

IntentFrame separates capability from authority: the tools (executor adapters) only know how to *do* things. The policy (deterministic gates + AI judgment) decides whether things *should* be done. The runtime is the only path between the two. No tool gets to vouch for itself.

The Actor SDK is the boundary between deterministic agent code and AI-decided operations. When a developer builds an agent, they route the LLM's chosen actions through `actor.submit()`:

```python
from intentframe_actor import Actor

actor = Actor(agent_id="invoice_bot", user_id=user_id)

# --- DETERMINISTIC CODE (runs freely, no IntentFrame involvement) ---
model = pipeline("text-extraction", model="invoice-parser-v3")
extracted = model(invoice_image)

# --- AI-DECIDED OPERATIONS (go through IntentFrame) ---
result = await actor.submit({
    "action": "APPEND_ROW",
    "target": "/expense_tracker.csv",
    "data": {"vendor": extracted["vendor"], "amount": extracted["total"]},
    "reason": "Recording processed invoice"
})
```

IntentFrame uses an SDK approach rather than an MCP gateway because a gateway can be bypassed:

| Aspect | MCP Gateway | IntentFrame SDK |
|---|---|---|
| Structural security | No — agent can call APIs directly | Yes — agent has zero execution capability |
| Bypass possible | Yes | No (within the SDK boundary) |
| Trust model | Surveillance (watching traffic) | Structural (architecture prevents bypass) |
| Credential isolation | No | Yes — only Executor holds credentials |
| Fail-closed | No | Yes |

> **MCP Gateway is surveillance — watching traffic and hoping the agent routes through it.**
> **IntentFrame SDK is structural — the agent has no other path to the executor.**

That distinction is the entire reason IntentFrame is an SDK, not a proxy. A gateway-style filter requires the agent to cooperate by routing every action through it. An SDK boundary requires the developer to cooperate at integration time (by routing AI-decided actions through `actor.submit()`), but once that cooperation is in place, the agent itself has no alternative execution path: it does not hold credentials, does not have direct IPC with the executor, and does not know where the credential vault or executor sockets live. The trust boundary is the SDK call, not a network filter that can be skipped.

The SDK approach means agents are structurally incapable of executing without going through the IntentFrame pipeline. The developer's deterministic code runs freely; the LLM's runtime decisions go through IntentFrame.

---

## The Deterministic Floor: `command_shield`

For `RUN_COMMAND` — the most dangerous action type because it spawns arbitrary shell commands — IntentFrame runs `command_shield` before any other evaluation. This is a deterministic inspection layer that:

- Decomposes command structure via bashlex AST parsing
- Normalizes obfuscation (`su""do` → `sudo`)
- Extracts inline interpreter payloads (`python -c "..."`, `bash -c "..."`)
- Inspects reachable code bodies through `inspect_code`
- Tags capabilities (`capability:read_only:filesystem_list`, `capability:filesystem_write`, `capability:network_bind`, etc.)
- Identifies edges (dynamic content: command substitution, variable expansion, pipes to interpreters)
- Emits structured signals: verdict (`SAFE` / `NEEDS_REVIEW` / `CATASTROPHIC`), capabilities, edges, code_intel findings

`CATASTROPHIC` verdicts end the pipeline immediately — no further evaluation, no AI, instant BLOCK.

`command_shield` cannot be prompt-injected because it is pure regex/AST evaluation with no AI component.

---

## The Fast-Path Security Model

Not every intent needs AI evaluation. The pipeline skips AI calls when it is provably safe to do so, using the `DeterministicGuardian`:

```
command_shield (L0) — produces CommandReport
    │  CATASTROPHIC → BLOCK immediately
    ▼
DeterministicGuardian (L3a) — consumes report + user policy
    ├─ BLOCK      ← permission / constraint / domain gate fires
    ├─ ALLOW      ← passive-read OR run-command read-only short-circuit
    └─ UNDECIDED  ← no deterministic verdict; falls through to AI
                   ▼
                Analysis Engine (L2) — LLM call
                   ▼
                AIGuardian (L3b) — LLM call
```

BLOCK and ALLOW end the pipeline — no AE call, no AI Guardian call, no LLM cost. Only UNDECIDED intents reach the AI path.

### Two ALLOW branches

**Branch A — Passive-Read ALLOW (action-keyed):**
Actions like `LIST_CALENDARS`, `READ_FILE`, `LIST_DIRECTORY`, `SEARCH_CONTACTS` that are curated pure reads. Two conditions must both hold: the action is in the developer-curated `_PRE_AE_SAFE_READS` set, AND the user's policy marks it `safe: true`. Neither alone is sufficient.

**Branch B — RUN_COMMAND Read-Only ALLOW (signal-keyed):**
For `RUN_COMMAND`, the fast-path keys off structural facts about the command itself — the `capability:read_only:*` family emitted by `command_shield`. Seven independent gates must all pass:

| Gate | What it checks |
|---|---|
| S1 | `command_shield` verdict is `SAFE` |
| S2 | A `capability:read_only:*` tag is present (positive structural fact) |
| S3 | No write/bind/exec/signal/spawn capabilities present |
| S4 | No `capability:network_probe:*` tag present |
| S5 | User's `deny_capabilities` is disjoint from report capabilities |
| S6 | No `edge:*` signal present (dynamic-content safety net) |
| S7 | No `code_intel` findings (resolved-body safety net) |

Every gate is a structural predicate decided deterministically. Nothing rides on an LLM. Commands like `ls -la`, `cat README.md`, `ps aux`, `git log --oneline` land here — instant ALLOW, zero LLM calls.

### What does NOT get a fast-path

There is no passive-write fast-path. Every mutating write (`WRITE_FILE`, `DELETE_FILE`, `SEND_EMAIL`, etc.), every user-IO action, and every action without a positive deterministic-ALLOW gate falls through to full AI evaluation. This is deliberate: writes change the user's world, so they always require semantic review.

### The `safe: false` routing invariant

Financial and consequential actions (`APPEND_ROW`, `PAY_INVOICE`, `SEND_EMAIL`, etc.) are declared `safe: false` in user policy at registration time. This routing decision is made **at policy definition time, not at runtime** based on what the agent claims.

A compromised agent that crafts a plausible-looking low-amount intent cannot bypass the AI layer by making the intent appear structurally clean. The `safe` flag was set by the user/developer before the agent ran — it cannot be influenced by agent-supplied fields.

This is architecturally important because it closes a class of attacks where the attacker makes everything look normal to skip AI review. The only way to reach the fast-path is: the action must be in the `_PRE_AE_SAFE_READS` set AND marked `safe: true` by the user. Both are developer/user decisions, not runtime agent decisions.

The 24-attack invoice suite (`demo/tests/test_attacks.py`, `test_advanced_attacks.py`, `test_redteam_attacks.py`) validates that mutating actions always reach the AI path when structurally valid — and that the AI layer catches semantic deception that deterministic gates cannot. See [docs/evidence.md § Suite 2](evidence.md#suite-2-the-invoicepayment-attack-suite) for the full breakdown.

---

## The AI Layers

When `DeterministicGuardian` returns UNDECIDED, the intent enters the AI path.

### Analysis Engine — "What will this action REALLY do?"

The Analysis Engine is a semantic AI component that produces a structured factual report. It does not apply policy. It answers: given this intent, what will actually happen to the user's world?

Output (Pydantic-structured `AnalysisReport`):
- Stated intent vs. actual behavior comparison
- Semantic domains (e.g., "spending", "deletion", "communication")
- Hidden behaviors detected (discrepancies between claimed and actual effects)
- Risk factors and reversibility assessment
- Scope analysis

All output fields are bounded by `AEFieldLimit` — no single field can exceed 600 characters, no list can exceed 10–15 items. This structurally limits the surface available for transitive injection.

#### Why temperature=0 and prompt design matter

The AE runs `gpt-4o-mini` at `temperature=0`. This is deliberate. Prompt and temperature serve different functions:

- **Prompt** shapes *where* the model concentrates probability mass — what it attends to and what analytical patterns it checks for. The AE prompt teaches three cross-checks: reason vs. data (catches Attack 15: reason says "$49.99", data is `$4,999`), key vs. value (catches Attack 17: vendor field contains a system policy dump), reason vs. target (catches `target=/etc/passwd` paired with `reason="reading expense report"`).
- **Temperature** controls how faithfully the model commits to that concentration during generation. `temperature=0` is greedy decoding — the model always picks the highest-probability token, so the same intent produces the same analysis on every run.

Together they are multiplicative: a strong prompt concentrates probability mass on the right analytical path, and `temperature=0` ensures the model commits to it every time. This is why Attack 2 reproduces 10/10 BLOCK across consecutive runs (see [docs/evidence.md § Reproducibility](evidence.md#reproducibility-10-consecutive-runs-of-attack-2)).

`temperature=0` is not truly deterministic — GPU parallelism, sparse Mixture-of-Experts routing, and floating-point precision contribute residual ~5% variation even at `temperature=0`. This is why deterministic gates (`command_shield`, constraint checks, domain modules) backstop the AI layers: when the LLM stage rigidly misses something, the structural floor still holds.

The Guardian uses a reasoning model (`gpt-5-mini`) which does not accept the `temperature` parameter; output variability is controlled via `reasoning.effort` instead.

#### What active_domains and intent_limits provide to the Guardian

The Guardian receives, alongside the AE's report, two policy-derived signals that are **independent of AE output**:

- **`active_domains`** — deterministically extracted from the user's policy by `_extract_active_domains()`. If the user has a `spending` intent limit, the `spending` domain is in `active_domains` regardless of whether the AE classified the action as spending. A poisoned AE that omits the spending classification cannot remove the limit.
- **`intent_limits`** — the user's natural-language semantic boundaries (`limit_id`, `domain`, `raw` text, optional `threshold`). Each limit is injected into the Guardian prompt as a trusted, named policy boundary. When the Guardian blocks, it cites the limit's `raw` text verbatim — the audit log shows which user policy was applied, not just "the AI said no."

This is why the `invoice-face-value` limit appears verbatim in every Attack 2 block message: it is the user's policy text, anchored in the policy registry, that the Guardian is enforcing — not a free-form AI judgment.

### Guardian — "Should we allow it?"

The Guardian applies user policy to the Analysis Engine's report plus the original intent. It makes the final ALLOW/BLOCK decision for the AI path.

The Guardian receives trusted context from two sources:
1. **Policy-declared domains** — deterministically extracted from user rules (not AI-generated)
2. **AE-classified domains** — Analysis Engine's semantic classification

The Guardian independently inspects untrusted intent fields (target, reason, data) — it does not blindly trust the AE report. If it identifies a relevant domain missing from earlier signals, it adds it before evaluating.

Output (Pydantic-structured `AIGuardianOutput`):
- `decision`: strictly "ALLOW" or "BLOCK" — anything else fails closed to BLOCK
- `reason`: required justification
- `policy_violated`: which policy was triggered (if BLOCK)
- `confidence`: 0.0–1.0
- `limit_violated`: which limit was breached (if applicable)

There is no field for a modified intent or modified payload. The Guardian cannot rewrite the action — it can only approve or reject the exact intent that already passed deterministic gates.

### Why AE and Guardian are separate

| Analysis Engine | Guardian |
|---|---|
| "What does this action REALLY do?" | "Should we ALLOW it?" |
| Semantic understanding | Policy enforcement |
| Outcome prediction | User preferences |
| Hidden behavior discovery | Risk thresholds |
| OUTPUT: Analysis Report | OUTPUT: Decision |

This separation enables defense-in-depth: if the AI is fooled on understanding, policies still enforce hard constraints. If policies have gaps, AI detection remains valid. No single component can both understand AND decide — preventing "benevolent overreach" where AI might override strict policies based on what it thinks is best.

---

## The Executor

The Executor is the sole entity with credentials and execution capability. It performs validated actions but does not judge whether they should happen.

```
HAS:     Credentials, execution capability, rollback ability
HAS NOT: Policy authority, judgment capability — does NOT question wisdom.
         Only executes what Guardian has validated.
```

For `RUN_COMMAND`, the Executor applies a kernel-enforced sandbox (macOS Seatbelt / `sandbox-exec`) to every subprocess. The sandbox profile is built inline based on what the pipeline approved — invisible to the agent, the pipeline, and the Guardian.

In the root-demo profile, the executor's `RUN_COMMAND` child subprocess can escalate through `sudo -n sandbox-exec`. But the rest of the stack — gateway, policy services, agent process — runs as the normal user. Root capability is intentionally scoped to the narrowest possible execution path.

---

## The No Self-IO Principle

No component of the IntentFrame pipeline — Guardian, Analysis Engine, Actor, or the Runtime itself — may trigger, consume, or act upon any resource or IO service.

```
WHO CAN USE RESOURCES:

  Agent (via IntentFrame pipeline)     ✓  Submits intents, receives results
  Executor (on validated intents)      ✓  The only component that touches resources

  Guardian                             ✗  Judges. Cannot act.
  Analysis Engine                      ✗  Understands. Cannot act.
  Actor                                ✗  Parses. Cannot act.
  Runtime                              ✗  Orchestrates the pipeline. Cannot act on resources.
```

This is not a guideline. It is a structural invariant.

Why it matters:

- **IntentFrame can't validate itself.** If the validator also submits intents, who validates those? The whole purpose is that no action reaches the real world without independent validation. The moment a pipeline component acts on its own, that action is unvalidated.
- **Auditability holds.** The audit log captures agent intents that flow through the pipeline. If Guardian made its own IO calls, those calls would be untracked side-channel actions.
- **Trust model holds.** The agent is untrusted; everything it does is validated. If Guardian acts on its own, those actions are unvalidated by definition.

If Guardian wants to ask the user a question, it cannot trigger `ASK_USER` directly. It returns BLOCK to the agent. The agent (the business logic expert) decides how to handle it — perhaps submitting an `ASK_USER` intent that itself goes through the full pipeline. The separation is clean: IntentFrame validates others. It cannot validate itself. Therefore it cannot act for itself.

---

## Action Families

IntentFrame supports two filesystem tool families:

- **Workspace/VFS tools** (`READ_FILE`, `WRITE_FILE`, `LIST_DIRECTORY`, etc.) — operate within a virtual filesystem mounted by the ResourceRegistry. Agents only see virtual paths mapped by the dashboard.
- **Host file tools** (`READ_HOST_FILE`, `WRITE_HOST_FILE`, etc.) — operate on the real filesystem with path constraints enforced by policy.

Real product profiles should usually expose only one family to a given LLM tool list. See [docs/vfs-vs-host-tools.md](vfs-vs-host-tools.md) for the design guidance and tradeoffs.

For terminal commands (`RUN_COMMAND`), the situation is different: terminal is the universal surface covering all workflows — dev work, sysadmin, devops, file management, automation, network ops, security, monitoring. IntentFrame validates every shell command through `command_shield` + `DeterministicGuardian` + AI layers rather than restricting the surface to a narrow set of typed operations.

---

## Fail-Closed By Default

```
Any failure, timeout, or error → BLOCK (never silent approval)

Validation failures    →  BLOCK
Timeouts               →  BLOCK or QUEUE
Uncertainty            →  BLOCK (agent can then ASK_USER if appropriate)
Missing validation     →  BLOCK (all stages required)
Guardian output error  →  Exception (fail-stop, not fail-open)
Decision not "ALLOW"   →  BLOCK (explicit approval required)

Absence of BLOCK ≠ ALLOW — explicit approval required at every stage.
```

---

## Audit Trail

Every intent's journey through the pipeline is recorded:

- `decision`: ALLOW or BLOCK
- `decision_path`: which layer decided (`command_shield`, `deterministic`, `fast_path`, `ai_path`)
- `matched_gate`: which specific gate triggered (for deterministic decisions)
- `ae_prompt_id` / `guardian_prompt_id`: which AI calls were made
- `confidence`: Guardian's stated confidence
- `reason`: why the decision was made
- Timestamps for each stage

Deterministic-fast-path decisions are reproducible by definition. AI-path decisions vary across runs (the Guardian genuinely evaluates each time), but the audit trail captures the full reasoning.

---

## Related Documents

- [docs/threat-model.md](threat-model.md) — what IntentFrame protects against and what it doesn't
- [docs/principles.md](principles.md) — core invariants stated concisely
- [docs/evidence.md](evidence.md) — test results and failure reports
- [docs/why-trust-ai-hybrid-intentframe.md](why_trust_ai_hybrid_intentframe.md) — why the AI hybrid model works
- [docs/why-not-injection-shield.md](why-not-injection-shield.md) — why no dedicated injection detector
- [docs/vfs-vs-host-tools.md](vfs-vs-host-tools.md) — workspace vs host filesystem tools
- [docs/terminal_use/current_pragmatic_choice.md](terminal_use/current_pragmatic_choice.md) — terminal policy decisions
- [docs/root_demo/executor-root-mode.md](root_demo/executor-root-mode.md) — root execution model
- [docs/faq.md](faq.md) — common objections answered
