# IntentFrame Principles

These are the core invariants of the IntentFrame architecture. Each is a structural guarantee, not a guideline. If any is violated, the security model is broken.

---

## 1. IntentFrame gates AI-decided actions, not all code

IntentFrame gates the non-deterministic operations an LLM chooses at runtime — the 5% of an agent program where the model makes decisions about what to do next. The 95% of deterministic, developer-written code runs freely without IntentFrame involvement.

Traditional security tools (code review, static analysis, unit tests, sandboxing) work on deterministic code. None work for AI-decided actions because the code doesn't exist until the LLM generates intent at runtime. IntentFrame fills this gap: runtime validation of non-deterministic decisions before they become real-world actions.

The developer's deterministic code is their responsibility — reviewable, testable, accountable. The LLM's runtime decisions are nobody's responsibility — until IntentFrame makes them its own.

---

## 2. Thought must not directly become action

An AI agent's reasoning must never result in direct execution. Every action the agent decides to take must pass through the IntentFrame pipeline as a structured Intent Frame — a proposal, not a command.

The agent cannot execute anything. It can only submit intents. Even if fully compromised and prompt-injecting every field, it cannot act — the pipeline must approve every action.

This is the fundamental separation: desire is separated from action, mediated by judgment. No shortcut path exists between the agent deciding "I should do X" and X happening in the world.

---

## 3. No Self-IO

No component of the IntentFrame pipeline — Guardian, Analysis Engine, Actor, or the Runtime itself — may trigger, consume, or act upon any resource or IO service.

- Guardian can judge but cannot act.
- Analysis Engine can understand but cannot act.
- Executor can act but cannot judge.
- No component crosses the line.

IntentFrame validates others. It cannot validate itself. Therefore it cannot act for itself. The moment a pipeline component acts on its own, that action is unvalidated by definition — and the system defeats its own purpose.

If Guardian wants to ask the user a question, it cannot trigger `ASK_USER` directly. It returns BLOCK to the agent. The agent (the business logic expert) submits an `ASK_USER` intent that itself goes through the full pipeline.

---

## 4. Policy immutability

Policies are static for the lifetime of a task. They are loaded at handshake and never change until the task completes. Nothing that happens during execution — no user response, no adapter result, no agent request — can alter, override, or extend the policies that Guardian enforces.

A user's "yes" to an `ASK_USER` prompt does not raise a hard limit. If max amount is $5K, a user accepting a $12K action does not unlock it. The response goes to the agent (business logic), but Guardian still enforces $5K.

This prevents the agent from socially engineering the user into policy changes through cleverly constructed prompts. With static policies, this attack is structurally impossible — no amount of prompt manipulation can get past the limit.

Policy changes are always out-of-band: the user adjusts settings before the next session, not during execution.

---

## 5. Deterministic before AI

Deterministic enforcement always runs first. AI evaluation only occurs for actions that pass all deterministic checks and cannot be decided without semantic judgment.

The two-layer model:

| Layer | Cost | Certainty | Can be prompt-injected? |
|---|---|---|---|
| Deterministic (permissions, constraints, domain gates, `command_shield`) | Cheap | Absolute | No |
| AI (Analysis Engine + Guardian) | Expensive | High but fallible | Theoretically possible |

If deterministic policy blocks, the AI never runs and cannot override. The AI can only allow or block actions that already passed structural checks. This means the AI's surface is shrunk to only the genuinely ambiguous cases where semantic judgment is required — reducing both cost and attack surface.

---

## 6. AI is bounded, not sovereign

The AI layers (Analysis Engine and Guardian) carry real authority for semantic judgment, but that authority is bounded:

- **Bounded inputs** — untrusted content in per-request randomized boundary tokens; structured fields only; AE output capped at `AEFieldLimit` (largest field: 600 chars).
- **Bounded outputs** — Pydantic schema constrains responses; no free-text execution instructions; no intent-modification field exists.
- **Bounded role** — AE understands, Guardian decides. Neither executes. Neither modifies policy. Neither self-issues IO.
- **Bounded scope** — AI only evaluates actions that passed deterministic gates. It rules on the surface deterministic enforcement can't cover, not on everything.

The AI is trusted for semantic review inside the policy envelope. It is not the root of trust for structural policy. The root of trust is: policy, deterministic enforcement code, executor isolation, and configured resource boundaries.

---

## 7. Executor as enforcement point

The Executor is the sole entity with credentials and real execution capability. It is the only component that touches the real world. This makes it the last physical enforcement point.

- The Executor acts but cannot judge — it executes what Guardian approves without questioning wisdom.
- For `RUN_COMMAND`, the Executor applies kernel-enforced sandboxing (macOS Seatbelt / `sandbox-exec`) to every subprocess.
- Credentials never leave the Executor — no other component has API keys, secrets, or permissions to act.
- The Executor cannot modify the intent — it receives the exact intent that passed through all prior gates.

The agent has no direct IPC or credential access to the Executor. Communication goes through the IntentFrame runtime.

---

## 8. Auditability

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
