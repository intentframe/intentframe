# IntentFrame FAQ

Common questions from skeptical readers, security engineers, and developers evaluating IntentFrame.

> **Looking for an intuitive framing before diving into the questions?** [docs/mental-models.md](mental-models.md) walks through seven analogies — pharmacy, contractor, accountant/CFO, financial advisor, licensed professional, fire, OS kernel — each with what it gets right and where it breaks down. Pick whichever fits how you already think.

---

## Q1. Is this just AI guarding AI?

The honest answer: yes, for the slice of decisions that reach the AI layer.

For structurally-invalid intents, deterministic gates block before any LLM runs. For structurally-valid mutating actions, the AI Guardian is the last decider within the policy envelope.

But this is not "one LLM watching another LLM's output." The Guardian is not merely rereading the Agent's story. It receives a forensic dossier — structured evidence from `command_shield`, capability tags, the Analysis Engine's bounded factual report, and policy-derived domain signals — that the Agent did not have and cannot directly rewrite.

The framing that matters:

> Policy shrinks the surface the AI is allowed to rule on. Inside that surface, the AI is the decider. The executor caps what any ruling can physically do. Deterministic layers hold regardless of whether any AI is fooled.

It is closer to maker-checker control in finance: the reviewer is not magically perfect, but the system constrains the reviewer with policy, procedure, evidence, limits, and audit.

Concrete proof: attacks 15 and 17 in `demo/tests/test_redteam_attacks.py` are structurally valid (under amount caps, allowed paths, correct action types) but semantically deceptive. Deterministic gates alone would ALLOW them. Only the AI layer catches them. See [docs/evidence.md § Semantic-Only Catches](evidence.md#the-semantic-only-catches-attacks-15-and-17).

See [docs/why-trust-ai-hybrid-intentframe.md](why_trust_ai_hybrid_intentframe.md) and [docs/why-not-injection-shield.md](why-not-injection-shield.md) for the full argument.

---

## Q2. What if the Guardian LLM is prompt-injected?

A compromised agent can inject any text into `reason`, `data`, and `target` fields. These fields flow into the Guardian's prompt. The defense is not "detect and filter injection" — it is structural:

1. **Five deterministic layers cannot be prompt-injected** — `command_shield`, `DeterministicGuardian`, Policy Registry floor, AE catastrophic path, adapter `quick_check()`. Each is pure code/regex/AST with no AI component.

2. **AE field bounds close the transitive path** — all AE free-text fields have `maxLength`/`maxItems` constraints (largest: 600 chars). No single field can carry a complete jailbreak payload (typical requirement: 800–1500+ chars). `_detect_overflow()` flags anomalies.

3. **Prompt hardening** — per-request randomized 32-hex boundary tokens mark untrusted content, immutable role anchoring refuses identity rewriting, sandwich-pattern closing reinforcement. The AI actively converts injection attempts into detection signals.

4. **Structured output** — Pydantic `output_type` constrains responses. A jailbroken AI that tries to output free text produces a schema validation error, not a valid governance signal.

5. **Fail-closed parsing** — anything not literally `"ALLOW"` (case-insensitive) maps to BLOCK. There is no "APPROVE", "YES", "PERMITTED" — only `ALLOW` passes.

A successful injection must fool the AE AND the Guardian AND produce valid Pydantic output in both cases AND not trigger any deterministic layer. Each layer is independent.

Empirically: the 24-attack invoice suite (`demo/tests/test_attacks.py`, `test_advanced_attacks.py`, `test_redteam_attacks.py`) defends **23/24, with 0 bypassed and 1 awaiting a planned cumulative-policy feature** (Attack 16 / salami slicing — see [docs/evidence.md § About the "1 Known Gap"](evidence.md#about-the-1-known-gap--attack-16-salami-slicing)). The 43-case transitive injection suite passes 39/43, with the 4 "failures" requiring pre-compromised AE state that is production-unreachable. Attack 2 (semantic-only defense) reproduces 10/10 BLOCK on consecutive runs.

---

## Q3. Why not only deterministic rules?

Rules are good for structure. They are weak at meaning.

A rule can check whether `amount > 5000`. It cannot reliably know that a vendor field contains hidden PII, or that a benign-looking browser action is actually spending money, or that the `reason` and `data` contradict each other.

From the tested attack suite: attacks 2, 6, 15, and 17 are structurally valid (under amount cap, allowed action type, correct file path) but semantically deceptive. Only the AI layer catches them. If the AI layer were removed, these attacks would execute.

- **Attack 15:** reason says "$49.99 office supplies", `data.amount` is $4,999. Under the $5k cap. Path is allowed. Deterministic ALLOW. AI catches the mismatch.
- **Attack 17:** vendor field contains `BEGIN_DUMP` of system policies. Amount is $1. Path is allowed. Deterministic ALLOW. AI catches the data exfiltration.
- **Attack 23:** 4 legitimate $49.99 payments then a $47,500 hit. Deterministic catches the $47.5k (over the cap), but the design lesson matters — Guardian evaluates each intent independently, with no memory of prior ALLOWs creating false trust. No "earned reputation" weakens future checks.

The right answer is both: deterministic enforcement for known structures, AI evaluation for meaning-level judgment. Neither alone is sufficient.

---

## Q4. Does this protect direct shell/file access outside IntentFrame?

IntentFrame's contract with the developer is one line: route every AI-decided I/O action through `actor.submit(...)`. That is the SDK boundary, and inside it there is no bypass path — the agent literally cannot execute without the runtime evaluating the intent first.

Outside the boundary, IntentFrame doesn't apply. If a developer writes `os.system("rm -rf /")` *directly* in their Python code — bypassing the Actor SDK entirely — IntentFrame never enters the picture for that line. The developer's own deterministic code is the developer's responsibility, the same way it would be without IntentFrame, and is handled by traditional security tooling (code review, static analysis, sandboxing).

This is the cost of the SDK approach vs. a gateway/proxy model. Both require developer cooperation — IntentFrame requires it earlier in the stack (at SDK integration time), gateway approaches require it at proxy configuration time. IntentFrame's advantage: the contract is exactly one method (`submit`), the integration is two-sided (your tool body calls it; nothing else has to change), and within the boundary the agent has no door to anywhere except `submit`. So as long as you funnel AI-decided I/O through it, no clever prompt and no LLM bug gets the agent past the runtime.

For the developer-side framing of this contract, see [`actor-sdk.md`](actor-sdk.md).

---

## Q5. What is the latency cost?

The "3x latency" framing is wrong. The actual cost depends on the action type:

| Action type | LLM calls IntentFrame adds | Why |
|---|---|---|
| Passive read (`READ_FILE`, `LIST_CALENDARS`, etc.) | **0** | DeterministicGuardian fast-path ALLOW. No AI runs. |
| Read-only shell command (`ls`, `cat`, `ps aux`, etc.) | **0** | `command_shield` capability tagging + DG fast-path. No AI runs. |
| Catastrophic pattern (`rm -rf /`, `sudo`, etc.) | **0** | `command_shield` blocks deterministically. No AI runs. |
| Permission/constraint violation | **0** | DG blocks deterministically. No AI runs. |
| Genuinely ambiguous mutation (write file, run novel command, send email) | **2** | Analysis Engine + AI Guardian both run. |

For most actions an agent takes — reads, lookups, known-safe commands — IntentFrame adds zero LLM calls via deterministic fast-paths. For the fraction that are genuinely consequential and ambiguous, it adds two small-model calls.

The added cost is often <20% of the agent's own cost (agent uses big model × big context; AE and Guardian use small model × focused prompt), not 3x. And for fast-path actions, it's literally 0%.

**Where it is honestly expensive:** bulk operations (1000 invoices each hitting AI layers), real-time interactive agents (the two AI calls — Analysis Engine + Guardian — add ~8–15s per consequential action at current API response times; for an autonomous agent working in the background this is acceptable, but it is noticeable in a synchronous interactive loop), first-time novel write patterns.

**Why it gets adopted anyway:** the cost of one wrong agent action (deleted files, leaked credentials, unauthorized payment, embarrassing email) exceeds thousands of validation calls. This is the same tradeoff as HTTPS, code review, 2FA, and database transactions — security overhead universally adopted when the cost of failure exceeds the cost of checking.

---

## Q6. Has this been audited?

Not yet. Current evidence is first-party tests and code-level validation. Independent audit is a future milestone before enterprise security claims.

What exists today: 220-intent root-demo test suite (100 attacks, 100 benign, 20 gray-area), 24-attack invoice/payment red-team suite, 43-case transitive injection test suite, prompt hardening unit tests, and the 2026-04-27 failure report with remediation. All results are publicly available in the repository.

---

## Q7. What is the biggest known gap?

Cumulative multi-intent abuse (salami slicing). Today the system mostly evaluates per intent. Five $4,000 transactions can each pass a $5,000 per-intent cap. A stateful policy ledger — tracking cumulative spending, action frequency, and session-level patterns — is needed to close this gap. It is planned, not shipped.

Other documented gaps: lookalike-domain trust (needs user-specific allowlists), enterprise policy governance (multi-tenant), off-host audit retention and external log signing (the local SHA-256 hash chain is shipped, but logs still live on the host), and novel `command_shield` surfaces that may fall through to AI review until capability tags are expanded.

See [docs/threat-model.md § Known Gaps](threat-model.md#known-gaps-owned-publicly) for the full list.

---

## Q8. How is this different from guardrail libraries?

Most "guardrail" libraries (NeMo Guardrails, Lakera, Prompt Security, etc.) sanitize prompt or output text. They sit at the LLM interface and filter content.

IntentFrame operates at the **execution boundary** — it doesn't care what the prompt said or what the model output. It cares: given this structured intent, what will it do to the user's world, and does user policy allow it?

| Aspect | Guardrail libraries | IntentFrame |
|---|---|---|
| Where they sit | LLM input/output | Execution boundary |
| What they inspect | Prompt text, model output | Structured intents (action + target + data + reason) |
| Architecture | Gateway/filter (surveillance) | SDK (structural enforcement) |
| Can be bypassed? | Yes — agent calls tools directly | No — within SDK boundary |
| Credential isolation | No | Yes — only Executor holds credentials |
| Deterministic layers | Usually none | 5+ independent layers, un-injectable |

IntentFrame doesn't care *why* the agent was compromised. It cares: given that it was, can the resulting action touch the user's world?

---

## Q9. Why doesn't IntentFrame just sandbox the agent's tools?

Because sandboxing is a *containment* model — let the action through, then restrict what it can do. IntentFrame is a *prevention* model — understand the action, block it if dangerous, execute it with full capability if safe.

Sandbox-every-tool gives you "limited but always available" capability: the agent can technically do something but only inside the sandbox's box. That works for an analyst running a Jupyter notebook on untrusted code. It does not work for an assistant that needs to read your real calendar, send a real email, run a real shell command, and pay a real invoice — those are the actions that have to actually happen for the agent to be useful, and a sandbox that strips them down to "limited" makes the agent useless.

Prevention flips the contract: the agent has *full* capability when behaving correctly, and *zero* capability when not. There is no "limited but always" middle. The pipeline (Command Shield, DeterministicGuardian, Analysis Engine, AI Guardian, adapter `quick_check()`) decides which side of that line each intent falls on.

The kernel sandbox under `RUN_COMMAND` (macOS Seatbelt) does exist, but it sits *underneath* the prevention pipeline as a non-negotiable safety net for the rare case where prevention fails. It is not the primary defense, and it is not applied to typed adapters (file, email, calendar, etc.) because those have no subprocess to confine — the adapter itself *is* the boundary.

See [principles.md § 2 — Prevention before containment](principles.md#2-prevention-before-containment) and [executor/security-model.md](executor/security-model.md#the-philosophy-prevention-not-containment) for the full argument.

---

## Q10. Does the executor run as root?

No. The executor service process is normally a normal-user process. Only the executor's `RUN_COMMAND` child sandbox subprocess can request root through `sudo -n sandbox-exec`, and only when:

1. The machine has been armed with the root-demo installer (`intentframe_setup_root_demo.sh`)
2. The executor profile explicitly asks for escalation
3. IntentFrame stands before that execution boundary — every command goes through the full pipeline first

The gateway, policy services, agent process, and executor service itself all run as the normal user. Root capability is intentionally scoped to the narrowest possible path.

Even when escalated, the subprocess is wrapped in a **macOS Seatbelt SBPL kernel sandbox** (`executor/sandbox/platforms/macos.py`) — a dynamically-generated profile with `(deny default)` and a curated allowlist that the kernel enforces regardless of the subprocess's UID. Root capability is necessary for some legitimate operations but does not mean unrestricted execution.

See [docs/root_demo/executor-root-mode.md](root_demo/executor-root-mode.md) for the full privilege model.

---

## Q11. What does IntentFrame not claim?

This list is the *epistemic* version: what we deliberately do not assert. The matching *operational* list — concrete attack categories that are out-of-scope for the boundary — lives in [docs/threat-model.md § Out-of-Scope Attacks](threat-model.md#out-of-scope-attacks). The README's "Does NOT protect" bullets are the high-impact subset of both. The three lists are intentionally redundant at different scopes; they should never contradict.

IntentFrame does not claim:

- The agent cannot be prompt-injected.
- The agent's model is safe or aligned.
- The Guardian or Analysis Engine LLMs are perfect.
- Every semantic attack will be caught.
- A hostile local root user (already root outside IntentFrame) is contained.
- Direct unmanaged agent I/O — side channels outside registered executors — is protected.
- Actions outside the SDK boundary (e.g., `os.system()` in developer-written code that bypasses `actor.submit()`) are governed.
- The current release is enterprise-complete (multi-tenant policy governance, RBAC, delegation are not shipped).
- The root demo evaluates the agent model — it evaluates the runtime boundary under hostile execution conditions, with a deterministic stub agent.
- The system has been independently audited by a third party.
- Cumulative multi-intent abuse (salami slicing) is solved — per-intent evaluation today, stateful tracking planned.
- An adaptive adversary with full system knowledge cannot eventually find inputs that fool the AI layers.
- Off-host audit log retention or external log signing is shipped (the local SHA-256 hash chain is — see [docs/threat-model.md § Shipped Hardening Beyond the Core Pipeline](threat-model.md#shipped-hardening-beyond-the-core-pipeline)).

The public release claim is narrower:

> AI-decided actions routed through the IntentFrame boundary can be constrained before execution by deterministic policy gates, semantic AI review, and executor boundaries. The system is fail-closed: any error, timeout, or ambiguity results in BLOCK, never silent approval.

That is concrete, testable, and falsifiable.

---

## Q12. Does this lock me into IntentFrame for tool capabilities?

Honestly: yes — at the runtime layer. This is the trade-off the design makes deliberately, and it deserves a straight answer.

The model is a singleton: one IntentFrame runtime per machine, one Executor, one credential vault, one audit chain, one policy surface. Every agent on the machine is a *client* of that runtime. That is what makes the security story tractable — **one runtime to vet, n agents to use freely** — but it also means agents become clients of the runtime instead of standalone artifacts. If your agent needs an action that the Executor doesn't support yet (a new SaaS API, a new device capability, a new file format), you don't add a function tool to your agent — you add a runtime-side adapter (~50–100 lines per [executor/architecture.md](executor/architecture.md)) and wire it into the action registry. It is small code, but it is *runtime-side* code.

Same shape of dependency exists with **MCP servers** (you depend on the MCP server author and the protocol), **Composio / Arcade.dev** (you depend on the platform, and your credentials live with them), **Kagent** (you depend on the runtime), **Apple Shortcuts** (you depend on Apple). The choice is which dependency to take, not whether to have one — anything that owns the credential boundary owns *some* dependency.

What we ship to make the trade-off honest:

- **AGPL-3.0** — anyone can fork and maintain the runtime independently of the original maintainer.
- **Small executor surface** — adapters are ~50–100 lines each; the executor core is small enough to fork and audit.
- **Config-driven action registry** — extending capabilities does not require modifying the executor core.
- **No agent-layer lock-in** — the seam is one method (`actor.submit({...dict...})`); re-pointing your agent at a different IntentFrame fork is a config change, not a rewrite.

What singletonness *gives* in return is the property no per-agent model gives: credentials, audit, and policy are unified at the device, not replicated across n agents that each have to be vetted independently. See [single-runtime.md](single-runtime.md) for the full development of this trade-off, including the migration friction sizing for retrofitting existing OSS agents.

---

## Q13. Why not just validate inline and execute in the same process?

You can. Most guardrail libraries work this way: `validate(action)` then `execute(action)` in the same tool body. For a single team with a vetted tool set where the threat model is "prevent accidents," it is sufficient.

Where inline validation fails structurally:

1. **The verdict is just a return value.** "If validator says no, skip execution" is enforced by code discipline. A forgotten `if`, a compromised dependency, a refactor, an exception handler that falls through — any of these can ignore the verdict. With a separate executor, the agent process has no path to credentials or I/O surfaces other than through the runtime.

2. **Intent ≠ implementation.** When `validate({SEND_EMAIL, to: alice})` returns OK and the tool then calls `smtp.send(...)`, nothing guarantees the validated payload matches what was sent. With a separate executor, the validated structured intent is the unit that travels and gets executed — the bytes the policy saw are the bytes that hit the wire.

3. **Credential reach.** In-process execution means the agent process holds credentials. Any reflection path — `os.environ`, `__import__('keyring')`, `ctypes`, a malicious transitive dependency — can siphon them. With a separate executor, the LLM-adjacent process never held the credentials. This is an address-space property, not a code-discipline property.

4. **N tools = N places to get it wrong.** Inline validation pushes the burden onto every tool author. Out-of-process execution turns "did you call the validator correctly?" into "did you submit an intent at all?" — and there's no other interface.

The analogy: inline validation is to the separate executor what client-side `if (user.isAdmin) deleteUser()` is to a server-side authorization check. Both look identical until an attacker calls the underlying primitive directly.

If your threat model includes prompt injection, compromised dependencies, or supply-chain attacks on the agent process, inline validation is insufficient regardless of how carefully tool authors write code.

---

## Q14. The executor is deterministic code — why does the process boundary matter?

Determinism describes what code computes. The process boundary describes what code is allowed to touch and who can interfere. Those are orthogonal.

What a separate process provides that a function call cannot:

- **Address-space isolation.** The agent cannot mutate the executor's policy module, replace its function table, or read its credential cache. In Python, `sys.modules`, `gc.get_objects()`, and import hooks make in-process "isolation" fictional against a motivated attacker.
- **Distinct OS-level identity.** The executor can run under a different Seatbelt/AppArmor profile or UID. You cannot apply different OS privileges to two function calls in the same process.
- **Serialization as enforcement.** IPC forces values to be serializable and schema-conformant. The executor cannot be given a closure, a callback, or a file descriptor the agent smuggles across. Structural anti-confused-deputy property.
- **Policy immutability.** Policy is loaded in the executor's memory — unreachable from the agent process. `policy.allow_all = True` in agent code does nothing.
- **Audit integrity.** Records are written by the executor as a side-effect of execution. The agent cannot suppress or forge them.
- **Failure containment.** Agent crashes, OOM, infinite loops — none take the executor down. Audit keeps flowing.

The process boundary is not there because the executor is clever. It is there because the boundary itself carries guarantees no in-process design can match.

---

## Q15. I can build this myself — subprocess for tools, a skeptical-agent monitor, credentials in env. Why IntentFrame?

For a single agent with a known tool set in a controlled environment, you should probably build it yourself. IntentFrame does not try to convince you otherwise for that case.

What IntentFrame buys over DIY:

1. **A red-teamed attack corpus.** 100 attacks, 9 initially missed, fixed, re-run. That failure-then-fix iteration is the thing your hand-rolled monitor has not been through. Most homegrown "skeptical-agent monitors" pass a few obvious tests and silently miss ARP spoofing, time-sync hijacks, base64 indirection, and unicode smuggling. The value is not the architecture; it's the **attack/defense iteration you dont need to do yourself.**
2. **A shared pattern across multiple agents.** If your company will eventually have 1 agent, build it yourself. If it will have 5+ (and almost every company will, within 18 months), you want one runtime, one audit chain, one policy surface, one place a security team can review — for the same reason no one runs five different authentication systems in production.
3. **A policy vocabulary that survives refactors.** A homegrown "if-this-then-that" check drifts. A framework with a real policy DSL (even an imperfect one) tends to keep its invariants over time. This is the same argument for using a real authz library vs. hand-rolled `if user.role == 'admin'` scattered across a codebase.
4. **Audit chain integrity.** "Subprocess + log writes" doesn't get you a tamper-evident hash chain. You can build one. Most teams don't.
5. **Outsourced security research labor.** Every new attack class published, every new prompt-injection trick, becomes someone else's problem to add to the corpus. That's the same reason you don't write your own crypto or your own OAuth library.

**On "credentials in env are safe enough":** env vars protect against accidentally committing secrets to git. They do nothing against prompt injection that convinces the agent to emit `subprocess.run("env", capture_output=True)`. If your agent reads external content (email, web, docs), you're one injected instruction away from exfiltration via the agent's own tool-call path. Out-of-process credential isolation eliminates that entire surface.

**When DIY genuinely beats IntentFrame today:** single agent, single tool set, no untrusted external content, macOS not required, you need it shipped this week, or your tool set is outside current adapter coverage.

---

## Related Documents

- [docs/threat-model.md](threat-model.md) — full threat model with in-scope / out-of-scope
- [docs/architecture.md](architecture.md) — system architecture
- [docs/principles.md](principles.md) — core invariants
- [docs/evidence.md](evidence.md) — test evidence and failure reports
- [docs/why-trust-ai-hybrid-intentframe.md](why_trust_ai_hybrid_intentframe.md) — the AI hybrid argument in depth
- [docs/why-not-injection-shield.md](why-not-injection-shield.md) — injection shield decision record
- [docs/single-runtime.md](single-runtime.md) — one runtime per machine; the singletonness property and its honest trade-offs
