# IntentFrame Public Release Expert Discussion Brief

Purpose: help answer live questions from security engineers, infra leaders, AI safety reviewers, and technically skeptical industry experts during an open discussion.

This is not marketing copy. It is the crisp, honest version of what IntentFrame claims, what it proves today, and where the gaps are.

---

## 1. Opening Position

IntentFrame is a runtime control boundary for AI-decided actions.

It does not claim the agent LLM is safe, unjailbreakable, or aligned. It assumes the agent may already be confused, compromised, prompt-injected, or hallucinating, and asks a narrower question:

> Before this agent action touches the user's world, does it pass policy, deterministic gates, semantic review, and executor constraints?

The system is best understood as post-compromise containment for agent actions, not prompt-injection prevention for the agent.

---

## 2. The Core Claim

### Falsifiable Claim

If an authenticated agent submits an action through the supported IntentFrame boundary, and that action violates configured structural policy, the protected side effect should not occur.

Examples:

- Action not in `allowed_actions` → blocked.
- File path outside allowed paths → blocked.
- Known amount above typed cap → blocked.
- Catastrophic terminal command → blocked before AI review.
- Executor sandbox / VFS boundary prevents access outside mounted resources.

### What Would Refute This

A single policy-violating action routed through the supported IntentFrame path that successfully causes the protected side effect.

---

## 3. What IntentFrame Does Not Claim

IntentFrame does not claim:

- The agent cannot be prompt-injected.
- The agent's model is safe.
- The Guardian or Analysis Engine LLMs are perfect.
- Every semantic attack will be caught.
- A hostile local root user is contained.
- Direct unmanaged agent I/O is protected.
- The current public release is enterprise-complete.
- The root demo evaluates the agent model.

The public release claim is narrower:

> AI-decided actions routed through the IntentFrame boundary can be constrained before execution.

---

## 4. The Trust Boundary

The boundary is:

```text
Untrusted agent
  → structured intent submission
  → IntentFrame runtime
  → deterministic gates
  → semantic review when needed
  → executor
  → protected resource
```

The agent is outside the trusted boundary.

The executor is the only component with real execution capability and credentials.

The Analysis Engine and Guardian can reason and decide, but they do not execute side effects.

If an agent has direct file, shell, browser, API, or credential access outside IntentFrame, those actions are outside the current security claim.

---

## 5. What Is Hard-Enforced Without AI

These are the strongest parts of the system:

- Deny-by-default `allowed_actions`.
- Typed per-action constraints.
- Path constraints.
- Known amount caps.
- Domain structural gates for critical domains.
- `command_shield` deterministic inspection for shell / terminal actions.
- Catastrophic command blocking before semantic review.
- Executor sandbox / VFS / capability boundaries.

If these gates block, the AI does not get to override them.

---

## 6. Where AI Is Load-Bearing

AI is load-bearing for semantic judgment.

Examples:

- The action is structurally allowed but dishonest.
- The reason says `$49.99`, but data writes `$4,999`.
- PII is hidden in a legitimate-looking field.
- A browser/API/file action has a meaning that cannot be inferred from action type alone.
- A generic command is not obviously catastrophic but needs contextual interpretation.

This is the honest answer to "isn't this AI guarding AI?"

Yes, the AI layer reviews AI-decided actions in some cases. But it is not unconstrained AI reviewing unconstrained AI. It is AI review inside a deterministic policy and executor boundary.

---

## 7. If the AI Reviewer Is Wrong

If the semantic AI layer wrongly allows an action, the blast radius is bounded by:

- The action already having passed structural policy.
- The executor's sandbox and mounted resources.
- Credential scope.
- Action-type dispatch.
- OS-level boundaries.

But the system can still fail on structurally valid semantic deception if the AI layer misses it.

That is not hidden. It is the core risk of using AI for semantic review.

---

## 8. Root Demo Positioning

The root demo is not a live jailbreak benchmark.

It is a crash test.

The demo assumes the agent may already be compromised and deliberately submits malicious intents through the same boundary a real agent would use.

The root demo proves:

- The whole stack is not running as root.
- The executor service is normally still a normal-user process.
- Only the executor's `RUN_COMMAND` child sandbox path can escalate through
  `sudo -n sandbox-exec`.
- Root capability is intentionally scoped.
- Known catastrophic commands are blocked before execution.
- Root-capable execution does not mean unchecked execution.
- Benign allowed root commands can run.
- Malicious root commands are blocked.

Current proof artifacts: `demo/tests/root_demo/results/dry_run.txt` and
`demo/tests/root_demo/results/real_run.txt` both record 100 / 100 adversarial
root-demo attack intents returning expected `BLOCK` after remediation. See
`docs/root_demo/PROOF.md` for the concise evidence package and privilege model.

The root demo does not prove:

- The agent model cannot be tricked.
- The Guardian LLM is impossible to prompt-inject.
- The sudoers setup is a defense against a hostile local shell user.
- IntentFrame replaces OS sandboxing, EDR, or MDM.

---

## 9. Questions Experts Will Ask

### Q1. What is your root of trust?

Policy, deterministic enforcement code, executor isolation, and configured resource boundaries.

The LLM is not the root of trust for structural policy. However, the LLM is trusted for semantic review inside the policy envelope.

### Q2. Can the AI Guardian override policy?

No. If deterministic policy blocks before AI review, the AI does not run and cannot override that block.

The AI can only allow or block actions that already passed structural checks.

### Q3. Can the AI Guardian modify the command or payload?

Current code does not give the AI Guardian a payload-modification field in its structured output. It can decide `ALLOW` or `BLOCK`; it cannot rewrite the intent.

### Q4. What if the Guardian emits garbage?

Non-`ALLOW` decisions fail closed to block. Hard parser / provider failure behavior should be verified and documented before stronger public claims.

### Q5. What if every LLM in the system fails?

Structural policy still holds: denied actions, disallowed paths, typed caps, domain structural gates, catastrophic command blocks, and executor boundaries.

Semantic deception may fail open if it is structurally valid and only detectable through semantic review.

### Q6. Why use AI at all?

Rules are good for structure. They are weak at meaning.

A rule can check whether `amount > 5000`. It cannot reliably know that a vendor field contains hidden PII, or that a benign-looking browser/API action is actually spending money, or that the reason and payload contradict each other.

### Q7. Is this just AI guarding AI?

The honest answer:

IntentFrame uses AI to review some AI-decided actions, but that review is bounded by deterministic policy and executor constraints.

It is closer to maker-checker control in finance: the reviewer is not magically perfect, but the system constrains the reviewer with policy, procedure, evidence, limits, and audit.

### Q8. What is the biggest known gap?

Cumulative multi-intent abuse, such as salami slicing.

Today the system mostly evaluates per intent. A stateful policy ledger is needed to block "five allowed transactions that collectively violate policy."

### Q9. Are your logs immutable?

Do not claim immutable unless cryptographic append-only storage, hash chaining, signing, or off-host retention exists.

Safe phrase:

> IntentFrame records an audit trail of decisions and reasons. Tamper-evident audit storage is a separate hardening area.

### Q10. Has this been independently audited?

If not, say:

> Not yet. Current evidence is first-party tests and code-level validation. Independent audit is a future milestone before enterprise security claims.

---

## 10. Known Gaps To Own Publicly

- Cumulative / stateful policy enforcement is not complete.
- Lookalike-domain trust requires user-specific allowlists.
- Enterprise policy governance is not complete.
- Tamper-evident audit logs should not be claimed unless implemented.
- External LLM timeout / outage behavior must be documented.
- First-party tests are not a substitute for third-party audit.
- Direct unmanaged agent I/O is outside the current boundary.

Owning these gaps makes the rest of the claim more credible.

---

## 11. What To Emphasize In The Meeting

Lead with:

- Post-compromise containment.
- Runtime enforcement before side effects.
- Deterministic gates before AI.
- AI only where semantic judgment is required.
- Executor as capability boundary.
- Known gaps are documented, not hidden.

Avoid leading with:

- "AI safety."
- "LLMs cannot be prompt-injected."
- "Fully autonomous secure agent."
- "Immutable logs" unless implemented.
- "Enterprise-ready security" unless policy governance, auth, audit, and recovery are complete.

---

## 12. Root Demo Talking Track

Use this sequence:

1. "We are not testing whether the agent model can be tricked. We assume it already is."
2. "The agent is untrusted and unprivileged."
3. "Only the executor command path has root capability."
4. "Every command still goes through IntentFrame."
5. "Known catastrophic actions are blocked before LLM review."
6. "Ambiguous actions go through semantic review."
7. "Allowed benign root actions can execute."
8. "Blocked malicious actions do not reach execution."
9. "This is a containment demo, not a model benchmark."

---

## 13. One-Sentence Answer For Skeptics

> IntentFrame does not make the agent trustworthy; it makes the agent's real-world actions pass through a policy-enforced runtime boundary before execution.

---

## 14. Strong Closing

The important shift is from trusting the agent to constraining the agent.

Today, most agent safety depends on prompt behavior and user review. IntentFrame moves part of that burden into software: structured intents, deny-by-default policy, deterministic gates, semantic review, executor boundaries, and audit.

That is the release claim. Not magic. Not perfect. But concrete, testable, and falsifiable.
