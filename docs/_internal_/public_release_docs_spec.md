# Public Release Docs Spec

Purpose: distill the private IntentFrame knowledge base into a small public documentation set for the initial OSS release.

The goal is not to publish every internal note. The goal is to make the public repo clearly explain what IntentFrame is, what it claims, how it works, what it does not claim, and what evidence supports it.

---

## Public Release Thesis

IntentFrame is a runtime control plane for AI-decided actions.

It assumes the agent may be confused, hallucinating, prompt-injected, or compromised, and asks a narrower question:

> Before this agent action touches the user's world, does it pass policy, deterministic gates, semantic review, and executor constraints?

IntentFrame does not make the agent trustworthy. It makes the agent's actions pass through a policy-enforced runtime boundary before execution.

---

## Public Doc Set

Initial public docs should be small:

1. `README.md`
2. `docs/architecture.md`
3. `docs/threat-model.md`
4. `docs/principles.md`
5. `docs/why-trust-ai-hybrid-intentframe.md`
6. `docs/evidence.md` or `docs/demo/root-demo.md`
7. `docs/quickstart.md`
8. `docs/faq.md`

Everything else can remain internal or become later deep-dive material.

---

## README.md

Audience: first-time visitor, GitHub skimmer, potential user, contributor, reviewer.

Must answer:

- What is IntentFrame?
- Why does it exist?
- What problem does it solve?
- What is the core security claim?
- How do I run it?
- Where do I read more?

Sections:

- One-line thesis
- Problem
- What IntentFrame does
- Minimal architecture diagram
- Quickstart
- What it protects
- What it does not protect
- Links to docs
- Status and license

Private concepts to distill:

- `Why-IntentFrame.md`
- `What-IntentFrame-Guards.md`
- `Intent-Based-Agent-Security-Pure-Concepts.md`

---

## docs/architecture.md

Audience: technical evaluator, contributor, security engineer.

Must answer:

- What are the main components?
- Where is the trust boundary?
- What does each layer do?
- Why can’t the agent act directly?
- Why is the executor the enforcement point?

Sections:

- Agent is untrusted
- Actor structures intent
- Command Shield / deterministic gates
- Analysis Engine explains behavior
- Guardian decides against policy
- Executor performs approved actions
- Audit/result path

Private concepts to distill:

- `How-The-System-Works.md`
- `System-Design-End-to-End.md`
- `core/layers/*`
- `No-Self-IO-Principle.md`

---

## docs/threat-model.md

Audience: security reviewers.

Must answer:

- What is the attacker?
- What is in scope?
- What is out of scope?
- What would refute the claim?
- What does IntentFrame not prove?

Sections:

- Core claim
- Threat model
- Trusted and untrusted components
- In-scope attacks
- Out-of-scope attacks
- Falsifiability
- Known gaps

Private concepts to distill:

- `extras/security_analysis.md`
- `public_release_expert_discussion_brief.md`
- root-demo proof docs
- due-diligence Q&A docs

---

## docs/principles.md

Audience: people evaluating whether the architecture is coherent.

Must answer:

- What are the core invariants?
- Why is this not just another guardrail library?
- What must never be violated?

Sections:

- IntentFrame gates AI-decided actions, not all code
- Thought must not directly become action
- No Self-IO
- Policy immutability
- Deterministic before AI
- AI is bounded, not sovereign
- Executor as enforcement point
- Auditability

Private concepts to distill:

- `No-Self-IO-Principle.md`
- `Policy-Immutability-Principle.md`
- `Fast-Path-Security-Model.md`
- `Domain-Hardening.md`
- `Policy-Enforcement-Model.md`
- `Intent-Frame.md`

Rule: each principle should be 1 short section, not a full essay.

---

## docs/why-trust-ai-hybrid-intentframe.md

Audience: skeptical technical reader.

Must answer:

- Isn’t this AI guarding AI?
- Why trust Guardian if the agent can be prompt-injected?
- Why use an LLM at all?
- Can AI override policy?
- What is the root of trust?

Sections:

- The objection
- The answer
- Root of trust
- Bounded AI role
- Structured inputs
- Deterministic gates
- Q&A
- Code references

Source:

- Existing `docs/why_trust_ai_hybrid_intentframe.md`

---

## docs/evidence.md or docs/demo/root-demo.md

Audience: reviewers who want proof.

Must answer:

- What has been tested?
- What failed?
- What was fixed?
- What does the demo prove?
- What does it not prove?

Sections:

- Evidence summary
- Root-demo claim
- 100-intent attack corpus
- 2026-04-27 failure report
- Remediation summary
- Current results
- What this does not prove

Private/public sources:

- `demo/tests/root_demo/docs/README.md`
- `2026-04-27-attack-sweep-host-impact.md`
- `root-demo-policy-remediation.md`
- `docs/root_demo/PROOF.md`
- `docs/root_demo/executor-root-mode.md`
- milestone docs

---

## docs/quickstart.md

Audience: builder trying the project.

Must answer:

- How do I install?
- What do I run?
- What output should I expect?
- How do I run tests/demo?
- What are common setup failures?

Sections:

- Requirements
- Install
- Run local demo
- Run tests
- Expected output
- Troubleshooting

Source:

- Current README / setup docs / demo docs

This doc must be verified from a fresh clone.

---

## docs/faq.md

Audience: skeptical reader who has common objections.

Suggested questions:

1. Is this just AI guarding AI?
2. What if the Guardian LLM is prompt-injected?
3. Why not only deterministic rules?
4. Does this protect direct shell/file access outside IntentFrame?
5. What is the latency cost?
6. Has this been audited?
7. What is the biggest known gap?
8. How is this different from guardrail libraries?
9. Does the executor run as root?
10. What does IntentFrame not claim?

Source:

- `_internal_/skeptical_security_questions.md`
- `security/red_team_due_diligence_qa.md`
- `public_release_expert_discussion_brief.md`

---

## What To Keep Internal

Do not publish raw:

- business strategy
- GTM plans
- investor outreach
- raw model/advisor debate
- "More Opus/Gemini/Claude" sections
- internal release planning
- unshipped roadmap gaps
- raw private philosophy docs unless distilled

These can later become blog posts or deep dives after public cleanup.

---

## Distillation Rule

Each private concept becomes one of:

- one paragraph in a public doc,
- one diagram,
- one evidence link,
- one FAQ answer,
- or nothing for initial release.

Initial public docs should prove coherence, not exhaustiveness.

---

## Success Criteria

The initial public docs are good enough when a serious reader can answer:

1. What is IntentFrame?
2. What security claim does it make?
3. What does it explicitly not claim?
4. How does the architecture enforce the claim?
5. What evidence supports it?
6. How do I run it?
7. How do I contribute or evaluate it further?