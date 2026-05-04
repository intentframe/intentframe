# Universal Security Due-Diligence Questions

Questions any serious reviewer should ask of *any* system that claims to
mediate dangerous actions — an EDR, an IAM gateway, a database firewall, a
WAF, a SIEM correlation engine, a sandbox, an agent runtime. Framed
**without** reference to product-specific terms (no "Guardian", "Analysis
Engine", "command_shield", etc.) — those are *answers*, not questions.

Each question is followed by what can be answered from the source chat about
IntentFrame (`fafd805a-...jsonl`) and the code paths it inspected. Where a
fact was not established, the answer is marked **`CANNOT BE ANSWERED FROM
AVAILABLE CONTEXT`** rather than guessed.

This document is the prerequisite to the product-specific Q&A in
[`red_team_due_diligence_qa.md`](./red_team_due_diligence_qa.md). If the
universal questions cannot be answered, the product-specific ones do not
matter yet.

---

## Section A — Claim and threat model

### Q1. State the security claim in falsifiable form. What single observation would refute it?

**Drawn from chat:** "If an authenticated client submits a request through
the supported channel that violates the configured structural policy
(allowed-operation list, per-operation constraints, structural domain rules,
sensitive-target floor), the underlying side-effect does not occur on the
protected resource."

**Refutation shape:** exhibit a single structurally-policy-violating
request that produces a side-effect.

The 24-attack red-team suite cited in chat is the project's own attempted
refutation. One documented failure (cumulative-spend bypass) is preserved
rather than hidden.

### Q2. What is the threat model? Who is the attacker, what capability is assumed?

**Drawn from chat:** the agent producing requests is the assumed adversary
— it may be confused, deceived, or fully compromised by upstream causes
(prompt injection, poisoned tool output, poisoned memory/RAG, hallucination,
buggy implementation). The control's job is to limit what that adversary
can cause on the protected resource.

**Out of scope:** attackers with local root on the host, OS-level exploits,
attackers who bypass the request channel entirely, supply-chain compromise
of the control plane itself.

### Q3. What are you explicitly NOT defending against?

Verified non-goals from project docs cited in chat:

- prompt injection of the agent itself,
- replacing OS sandboxing, EDR, MDM, or human approval,
- actions that bypass the request channel (direct unmanaged tool access,
  side channels, out-of-band local shell),
- supporting every developer/admin workflow today,
- evaluating the agent's chosen LLM model.

Hold the project to this list. Wider claims are marketing, not engineering.

---

## Section B — Trust topology

### Q4. What is in the trusted computing base?

**In TCB (verified):** the runtime decision components, the executor process,
the configured policy.

**Out of TCB (verified):** the agent.

**Not enumerated in chat — treat as TCB by default until proven otherwise:**
the Pydantic library used for output validation, the external LLM API used
for semantic review, the host OS kernel, the policy storage layer, the HTTP
transport between agent and runtime, the Unix-domain-socket transport between
runtime and executor.

→ **TCB is partially specified.** Require an explicit, complete TCB list
before relying on the security claim.

### Q5. Where is the trust boundary, and what crosses it?

Verified topology: untrusted agent → HTTP → trusted runtime → UDS → trusted
executor → host resource.

Crossings are structured: typed requests inbound, structured ALLOW/BLOCK +
result outbound.

The cryptographic strength of the HTTP and UDS boundaries (mutual auth,
integrity, replay protection): **CANNOT BE ANSWERED FROM AVAILABLE
CONTEXT.**

### Q6. How is the requesting actor authenticated?

The chat references an "Actor handshake" and "policy-bound session," but the
cryptographic mechanism (token issuance, mTLS, signed nonce, session
lifetime, revocation) was not surfaced. **CANNOT BE ANSWERED FROM AVAILABLE
CONTEXT.**

### Q7. How is authorization expressed and enforced?

Verified: deny-by-default per-user `allowed_actions` map; typed per-operation
constraints (numeric caps, path constraints, capability denylists);
structural domain modules that can hard-gate independent of constraints.
Authorization is consulted on every request, before any semantic review.

---

## Section C — Failure modes

### Q8. Fail-open or fail-closed?

| Failure | Behavior |
|---|---|
| Decision string not literally `"ALLOW"` | Fail-closed → BLOCK (verified) |
| Decision payload fails schema validation | Fail-stop → exception, no execution. No controlled BLOCK. (Verified; chat flagged this as a hardening gap.) |
| External LLM API unreachable / slow / refuses | **Not verified** — CANNOT BE ANSWERED |
| Policy store unreachable | **Not verified** — CANNOT BE ANSWERED |
| Executor unreachable | **Not verified** — CANNOT BE ANSWERED |

The verified path is clean. The unverified paths are where a reviewer should
push.

### Q9. What is the blast radius if the central decision component is fully compromised?

Verified: a fully-compromised semantic-review layer can wrongly ALLOW any
request that already structurally passed the deterministic pre-filter
(operation allowed, under amount/path/capability constraints, no
sensitive-target violation, no domain-structural failure).

It cannot:

- modify the request (the output schema has no payload-modification field;
  the modification field on the result type is verified as never-set in
  current code),
- escape the executor's capability ceiling (sandbox profile, virtual-filesystem
  mounts, credential vault scope, action-type dispatch).

The blast-radius case worth modeling: a structurally-valid,
semantically-deceptive request just under every cap.

### Q10. Show me a case where the control demonstrably DID NOT WORK.

Verified, preserved as published failures:

- **Cumulative-spend bypass.** Per-request policy without a cumulative
  ledger: five $4,000 requests pass a $5,000 per-request cap.
- **Lookalike-domain trust failure.** A vendor domain a human user would
  have caught was not caught semantically; closing it requires a per-user
  allowlist, not stronger AI judgment.
- **Hand-fabricated AE-bypass experiments.** Explicitly hypothetical and
  documented as not production-representative.

That these are surfaced rather than hidden is itself a positive signal
about the project's failure-mode discipline.

### Q11. What is the recovery procedure after a confirmed compromise of the control plane itself?

Detection, containment, key / credential rotation, policy reset, audit-log
forensic preservation — **CANNOT BE ANSWERED FROM AVAILABLE CONTEXT.**

---

## Section D — Determinism, reproducibility, audit

### Q12. Are decisions deterministic, probabilistic, or non-deterministic? What is the variance?

Hybrid:

- **Deterministic** for permission / constraint / domain / sensitive-target
  gates, command-shape inspection, passive-read fast-path, read-only
  command fast-path.
- **Non-deterministic (live LLM)** for semantic analysis and validation.

Observed variance from chat-cited 10-run replay of one semantic-deception
attack: same BLOCK decision every run, rationale text varies between runs.
Outcome-stable, surface-variant.

Whether the LLM call is at temperature 0 (which would tighten
reproducibility): **not verified** — CANNOT BE ANSWERED.

### Q13. Can decisions be reproduced from logs alone, after the fact?

- Deterministic-path decisions: yes — decision path, matched gate, reason
  are recorded.
- Semantic-path decisions: outcome stable on replay; rationale text not
  bit-reproducible. Without temperature verification, full bit-
  reproducibility cannot be claimed.

### Q14. Are logs tamper-evident? Can a compromised system erase its own trail?

The chat refers to logs as "auditable" and "immutably logged" but does not
show the underlying mechanism (append-only store, hash chain, signed
entries, off-host shipping, retention policy). **CANNOT BE ANSWERED FROM
AVAILABLE CONTEXT** — and this is load-bearing for any post-incident story.

### Q15. Is there a time-of-check / time-of-use gap between decision and execution?

Partial:

- The request the executor receives is provably identical to the one that
  passed the gates (no in-flight modification field is ever populated).
- The executor resolves paths, mounts, and credentials at *execute* time,
  not at check time. Whether path resolution at execute time can produce a
  different physical target than what was authorized at check time, and
  whether credentials in scope at check time match those at execute time,
  was not surfaced.

→ **PARTIALLY ANSWERED.** Intent-identity invariant: verified.
Resolution-timing invariant: not verified.

---

## Section E — Configuration integrity

### Q16. What protects the policy itself from being silently modified?

Storage location, integrity protection (signature / hash / file mode),
change-control workflow, policy version provenance: **CANNOT BE ANSWERED
FROM AVAILABLE CONTEXT.**

A control plane whose policy can be silently rewritten by a local-file-access
attacker has no security claim left. This is the question that should be
answered before any deployment.

### Q17. Who can change policy, through what interface, with what authorization?

**CANNOT BE ANSWERED FROM AVAILABLE CONTEXT.**

The chat establishes "Policy Immutability" *for the lifetime of a task* (a
user "yes" mid-task does not raise a hard cap), but says nothing about the
policy-change authority surface itself.

### Q18. How is the system itself updated, and what is the supply-chain trust story?

Update channel, signing of releases, dependency pinning, build
reproducibility, transitive-dependency audit cadence: **CANNOT BE ANSWERED
FROM AVAILABLE CONTEXT.** A serious gap for any control plane.

---

## Section F — Data and host boundary

### Q19. What sensitive data flows through the system, and how is it handled in transit and at rest?

Verified data-in-flight: untrusted agent-controlled `reason` and `data`
reach the semantic layers; structured analysis output and decision records
flow to the executor and audit log.

In-transit encryption details, at-rest encryption of audit logs / policy /
credential vault, PII-redaction-in-logs policy: **CANNOT BE ANSWERED FROM
AVAILABLE CONTEXT.**

### Q20. What is below the application boundary — what host-OS / kernel-level defenses are assumed?

Verified: macOS `sandbox-exec` profile gates the executor's privileged
command path; virtual filesystem mounts gate file access; adapter dispatch
restricts action types.

Beyond macOS sandbox-exec, no kernel-level defenses are claimed. The control
plane explicitly does *not* substitute for OS sandboxing, EDR, or MDM.

### Q21. What is the insider / local-admin story?

An attacker with local root, kernel exploit, or arbitrary code execution
as the runtime/executor process is **out of scope** by design. The system
defends *containment of the agent*, not containment of an OS-level
attacker. Owned in the project's non-goals — but a reviewer should be sure
the deployment context matches.

---

## Section G — Operations

### Q22. What is the availability / denial-of-service posture?

Verified: malformed semantic output is fail-stop, not fail-open.

Behavior under request flood, large-input DoS against the semantic layer
(which calls an external LLM API), token-budget exhaustion, queue
saturation, sustained slow requests: **not surfaced** — CANNOT BE ANSWERED.

### Q23. What is the rate of false-positive (over-block) and false-negative (under-block) in production traffic?

**CANNOT BE ANSWERED FROM AVAILABLE CONTEXT.**

### Q24. Where does the security guarantee depend on external services outside your control?

The semantic-review layer depends on an external LLM API. The deterministic
envelope does not.

| External API behavior | Effect on control |
|---|---|
| Malformed output | Fail-stop (verified) |
| Refusing string | Mapped to BLOCK (verified — "refuse"-style strings ≠ "ALLOW") |
| Slow / timed-out | **Not verified** — CANNOT BE ANSWERED |
| Adversary-controlled | Reviewer should treat the semantic layer as best-effort and rely on the deterministic envelope for hard guarantees |

### Q25. Is there independent third-party verification (audit, pentest, formal proof, bug bounty)?

**CANNOT BE ANSWERED FROM AVAILABLE CONTEXT.** Only first-party tests are
cited.

A reviewer at any seriousness threshold should require external verification
before treating the security claim as load-bearing.

---

## Reviewer's reading

The verified facts paint a defensible *shape*: a deterministic structural
envelope around a probabilistic semantic layer, with a capability-bounded
executor.

The honest gaps cluster in three places:

1. **Transport authentication and integrity** (Q5, Q6).
2. **Configuration integrity at rest** (Q14, Q16, Q17, Q19).
3. **Operational posture** — DoS, supply chain, third-party verification,
   recovery (Q11, Q18, Q22, Q23, Q25).

Any reviewer should treat those three clusters as prerequisite. The
product-specific Q&A in
[`red_team_due_diligence_qa.md`](./red_team_due_diligence_qa.md) only
becomes load-bearing once the universal questions above are answered or
explicitly accepted as out-of-scope for the deployment.
