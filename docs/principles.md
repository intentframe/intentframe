# IntentFrame Principles

IntentFrame is a **runtime security control plane for AI-decided actions**. The effect of that control plane 
is that it automates the human oversight you would otherwise perform manually — reading every action, applying 
judgment, clicking approve or reject. The agent does the work; IntentFrame automates the supervision.

Our goal is **full delegatable autonomy** for AI agents — the same kind of autonomy that licensed professionals (surgeons, pilots, engineers) already have, brought into being for AI agents for the first time. The means is **structural supervision**: pre-declared policy, deterministic gates, semantic review, executor isolation, and an immutable audit trail. The agent stays operationally autonomous; the structure holds the boundaries. See [autonomy.md](autonomy.md) for the full thesis.

The principles below are the structural invariants that make that supervision trustworthy. Each is a structural guarantee, not a guideline. If any is violated, the model is broken — and the system collapses back into one of the two unscalable alternatives: trust by faith, or manual approval of every action.

---

## 1. IntentFrame gates AI-decided actions, not all code

IntentFrame applies structural supervision to the non-deterministic operations an LLM chooses at runtime — the 5% of an agent program where the model decides what to do next. The 95% of deterministic, developer-written code runs freely. The agent's reasoning, planning, and tool selection are all uncovered: the agent decides everything *operationally*, and only when an action would touch the user's world does the pipeline render a judgment.

```
┌──────────────────────────────────────────────────────────────┐
│  A REAL AGENT PROGRAM                                         │
│                                                               │
│  95% DETERMINISTIC CODE (developer-written)                   │
│  ├── Download models from HuggingFace                         │
│  ├── Connect to APIs the developer wired up                   │
│  ├── Parse JSON, validate schemas                             │
│  ├── Manage local state in workspace                          │
│  ├── Run inference on local models                            │
│  ├── Log, retry, handle errors                                │
│  └── All predictable. All reviewable. All testable.           │
│                                                               │
│  5% NON-DETERMINISTIC (AI-decided)                            │
│  ├── "I should read the user's tax documents"                 │
│  ├── "I should send an email to the user's boss"              │
│  ├── "I should delete these old files"                        │
│  ├── "I should approve this $12,000 expense"                  │
│  └── Nobody coded these. The LLM chose them at runtime.       │
│                                                               │
│  IntentFrame gates the 5%. The 95% runs freely.               │
└──────────────────────────────────────────────────────────────┘
```

Traditional security tools (code review, static analysis, unit tests, sandboxing) work on deterministic code. None work for AI-decided actions because the code doesn't exist until the LLM generates intent at runtime. You cannot code-review a decision that hasn't been made yet. You cannot write a unit test for an action the LLM hasn't chosen yet. IntentFrame fills this gap: structural supervision of non-deterministic decisions, applied at the moment they would become real-world actions.

The developer's deterministic code is their responsibility — reviewable, testable, accountable. The LLM's runtime decisions had no responsible structure — until IntentFrame supplied one.

> Traditional security handles deterministic code. IntentFrame handles non-deterministic decisions. Together, the whole agent program is covered — and the agent retains full operational autonomy over the part where autonomy actually matters (reasoning, planning, iteration), with structural supervision only at the boundary where actions touch the world.

---

## 2. Prevention before containment

IntentFrame is a *prevention* system, not a *containment* system. The pipeline exists to detect and block dangerous actions before they execute — not to let actions through and restrict their consequences afterwards.

| Prevention model (IntentFrame) | Containment model (traditional sandboxing) |
|---|---|
| Understand → Block if dangerous → Execute if safe | Let action through → Restrict what it can do |
| Everything reaching the executor is guaranteed safe | Executor must restrict every action |
| Executor runs with full privileges | Executor runs with limited privileges |
| Agent has effective root access — through the pipeline | Agent has restricted access — limited by sandbox |

This is why the prevention pipeline (`command_shield`, `DeterministicGuardian`, Analysis Engine, AI Guardian, adapter `quick_check()`) is the product. The kernel sandbox under `RUN_COMMAND` is a non-negotiable safety net for the rare cases where prevention fails — not the primary defense.

The choice has direct consequences. Containment-based agent security limits agent capability by construction: the more you sandbox, the less the agent can do, even when behaving correctly. Prevention-based security allows full capability when the agent is behaving correctly and zero capability when it isn't. There is no "limited but always available" middle state — the gate is open for safe actions and closed for unsafe ones.

> Prevention gives the agent maximum capability. Containment restricts it. IntentFrame chooses prevention because that is the only model where full capability and full safety can coexist.

For the philosophy applied to `RUN_COMMAND` specifically — the only action type that requires both prevention and containment — see [executor/security-model.md](executor/security-model.md#the-philosophy-prevention-not-containment).

---

## 3. Thought must not directly become action

An AI agent's reasoning must never result in direct execution. Every action the agent decides to take must pass through the IntentFrame pipeline as a structured Intent Frame — a proposal, not a command.

The agent cannot execute anything. It can only submit intents. Even if fully compromised and prompt-injecting every field, it cannot act — the pipeline must approve every action.

This is the fundamental separation: desire is separated from action, mediated by judgment. No shortcut path exists between the agent deciding "I should do X" and X happening in the world.

---

## 4. No Self-IO

No component of the IntentFrame pipeline — Guardian, Analysis Engine, Actor, or the Runtime itself — may trigger, consume, or act upon any resource or IO service.

- Guardian can judge but cannot act.
- Analysis Engine can understand but cannot act.
- Executor can act but cannot judge.
- No component crosses the line.

IntentFrame validates others. It cannot validate itself. Therefore it cannot act for itself. The moment a pipeline component acts on its own, that action is unvalidated by definition — and the system defeats its own purpose.

If Guardian wants to ask the user a question, it cannot trigger `ASK_USER` directly. It returns BLOCK to the agent. The agent (the business logic expert) submits an `ASK_USER` intent that itself goes through the full pipeline.

---

## 5. Policy immutability

Policies are static for the lifetime of a task. They are loaded at handshake and never change until the task completes. Nothing that happens during execution — no user response, no adapter result, no agent request — can alter, override, or extend the policies that Guardian enforces.

A user's "yes" to an `ASK_USER` prompt does not raise a hard limit. If max amount is $5K, a user accepting a $12K action does not unlock it. The response goes to the agent (business logic), but Guardian still enforces $5K.

This prevents the agent from socially engineering the user into policy changes through cleverly constructed prompts. With static policies, this attack is structurally impossible — no amount of prompt manipulation can get past the limit.

Policy changes are always out-of-band: the user adjusts settings before the next session, not during execution.

### What lives inside a policy

A user policy combines three kinds of rules, each enforced by a different layer:

| Rule type | Where it lives | What it does | Enforced by |
|---|---|---|---|
| `allowed_actions` | `UserPolicy` | Permission map: which `ActionType`s are allowed at all (deny-by-default), and per-action `safe` flag + per-category `constraints` (paths, recipients, amounts) | Deterministic — `DeterministicGuardian` permission + constraint checks |
| `domain_constraints` | `UserPolicy` (per critical domain — finance, deletion) | Typed structural rules: `max_amount`, `allowed_currencies`, `allowed_recipients`, `block_irreversible` | Deterministic — domain modules in `intentframe_components/guardian/domains/` |
| `intent_limits` | `UserPolicy` | Cross-cutting semantic boundaries written as natural language with structured metadata: `limit_id`, `domain` (e.g., `spending`), `raw` text, optional `threshold`, `effect` | Semantic — injected into Guardian's prompt as a trusted, named policy boundary the Guardian cites verbatim when it blocks |

Domain modules can BLOCK on structural violation but never ALLOW. Passing the structural check means "structurally valid," not "safe" — AI still evaluates everything else. Intent limits catch cases that structural rules cannot reach: an `HTTP_POST` to a payment API can be classified as "spending" by the Analysis Engine and bounded by the same `max-spend-per-txn` limit that catches `PAY_INVOICE`, even though there is no per-category amount constraint on `HTTP_POST`.

The `active_domains` set passed to Guardian is also part of policy, not AI: it is **deterministically extracted** from the user's policy rules (`_extract_active_domains()`) and injected into Guardian's context regardless of how the Analysis Engine classified the action. A poisoned AE that misses the "spending" classification cannot remove the spending limit — the limit is anchored in policy, not in AE output.

---

## 6. Deterministic before AI

Deterministic enforcement always runs first. AI evaluation only occurs for actions that pass all deterministic checks and cannot be decided without semantic judgment.

The two-layer model:

| Layer | Cost | Certainty | Can be prompt-injected? |
|---|---|---|---|
| Deterministic (permissions, constraints, domain gates, `command_shield`) | Cheap | Absolute | No |
| AI (Analysis Engine + Guardian) | Expensive | High but fallible | Theoretically possible |

If deterministic policy blocks, the AI never runs and cannot override. The AI can only allow or block actions that already passed structural checks. This means the AI's surface is shrunk to only the genuinely ambiguous cases where semantic judgment is required — reducing both cost and attack surface.

### How the layers compose: ALLOW = AND, BLOCK = OR

The control flow across layers is conjunctive, not unanimous-vote-or-else:

- **Deterministic BLOCK** → final. AI never runs.
- **Deterministic pass** → AI still evaluates; AI can BLOCK on its own judgment (e.g., semantic deception that structural checks cannot see).
- **Neither layer can override the other into ALLOW.** No deterministic pass forces AI to allow. No AI ALLOW overrides a deterministic BLOCK.

> **ALLOW requires *all* layers to agree. BLOCK requires only one.**

This is the same shape as defense-in-depth in any security system: many ways to fail safely, only one way to succeed. The AI does have *block authority* in its bounded role. What it lacks is *allow-override authority* over a deterministic block.

---

## 7. AI is bounded, not sovereign

The AI layers (Analysis Engine and Guardian) carry real authority for semantic judgment, but that authority is bounded:

- **Bounded inputs** — untrusted content in per-request randomized boundary tokens; structured fields only; AE output capped at `AEFieldLimit` (largest field: 600 chars).
- **Bounded outputs** — Pydantic schema constrains responses; no free-text execution instructions; no intent-modification field exists.
- **Bounded role** — AE understands, Guardian decides. Neither executes. Neither modifies policy. Neither self-issues IO.
- **Bounded scope** — AI only evaluates actions that passed deterministic gates. It rules on the surface deterministic enforcement can't cover, not on everything.

The AI is trusted for semantic review inside the policy envelope. It is not the root of trust for structural policy. The root of trust is: policy, deterministic enforcement code, executor isolation, and configured resource boundaries.

---

## 8. Executor as enforcement point

The Executor is the sole entity with credentials and real execution capability. It is the only component that touches the real world. This makes it the last physical enforcement point.

- The Executor acts but cannot judge — it executes what Guardian approves without questioning wisdom.
- For `RUN_COMMAND`, the Executor applies kernel-enforced sandboxing (macOS Seatbelt / `sandbox-exec`) to every subprocess.
- Credentials never leave the Executor — no other component has API keys, secrets, or permissions to act.
- The Executor cannot modify the intent — it receives the exact intent that passed through all prior gates.

The agent has no direct IPC or credential access to the Executor. Communication goes through the IntentFrame runtime.

---

## 9. Auditability

Every intent's journey through the pipeline is recorded with:

- Which decision was made (ALLOW / BLOCK)
- Which layer decided (command_shield / deterministic / fast_path / ai_path)
- Which specific gate triggered (for deterministic decisions)
- What reasoning was given (for AI decisions)
- Timestamps and prompt IDs for reproducibility

Deterministic-fast-path decisions are reproducible by definition — same input always produces same output. AI-path decisions vary across runs, but the audit trail captures the full reasoning each time.

The audit trail exists for accountability, debugging, and trust verification — not for real-time intervention. IntentFrame decides before execution, not after. The audit proves what happened and why, so failures can be diagnosed and coverage can be expanded.

---

## The Combined Invariant

> No single intelligent entity can simultaneously define, validate, and execute intent.

The agent thinks. The Actor parses. The Analysis Engine understands. The Guardian judges. The Executor acts. No component crosses the line. The pipeline is a passive intermediary — it validates others, it does not act for itself, and its decisions are recorded.

These invariants are not aspirational. They are structural properties of the architecture. Violating any of them would require changing the code, not just crafting clever inputs.

---

## Related Documents

- [docs/architecture.md](architecture.md) — full architecture with implementation details
- [docs/threat-model.md](threat-model.md) — what these principles protect against
- [docs/why-trust-ai-hybrid-intentframe.md](why_trust_ai_hybrid_intentframe.md) — why bounded AI works
- [docs/why-not-injection-shield.md](why-not-injection-shield.md) — why structural defense over detection
