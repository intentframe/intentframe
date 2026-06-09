# What About Prompt Injection?

Prompt injection is not a side issue for IntentFrame. It is one of the main reasons the system exists.

The honest answer is not "IntentFrame cannot be prompt-injected." That would be too strong. Agents can be prompt-injected. AI reviewers can be fooled in principle. A white-box attacker who knows IntentFrame exists, knows the open-source prompts, targets the agent, Analysis Engine, and Guardian together, and uses a compromised agent to fetch second-stage malicious documents is a real threat model.

The defensible claim is narrower:

> IntentFrame does not make prompt injection impossible. It makes a successful prompt-injection bypass require a chained failure across the agent, the Analysis Engine, and the Guardian, while constraining what each failed component can pass to the next one.

That is a real reduction in risk. It is not a formal guarantee.

---

## Can you guarantee Intentframe is Injection-Proof? — No. Here's the honest claim instead.
You cannot guarantee an LLM is injection-proof. LLMs are statistical; "we wrote a strong system prompt" is never a proof. Anyone who tells you the AE cannot be injected is overclaiming.

What we can defensibly claim at the AI layer is narrower and stronger-sounding because it's true:

* The architecture converts a single point of failure into a conjunction of independent-ish, individually-unlikely events.
* Even a successful injection is blast-radius bounded by structured output (no decision field, enum sanitization, length caps) — success doesn't equal payout.
* The empirical surface (23/24 defended; live 39/43 where the 4 are hand-crafted-past-the-AE or missing-context, not prose injections) supports "very hard," not "impossible."
The part that converts "very hard" into an actual guarantee is precisely the deterministic floor + executor caps. That's why they exist: the AI layer's job is accuracy and catching semantic attacks; the floor's job is to bound the worst case regardless of how the dice land on the models. Remove the floor and the honest word is "multiplicatively unlikely and bandwidth-bounded," not "guaranteed."

## The Compounding Chain

Why is injecting the agent, AE, and Guardian **simultaneously** the hard part? Because each stage must succeed for the attack to pay out, and each stage has a different job.

In the simplest case, the agent knows nothing about IntentFrame. Its system prompt only hardens its own generic `trusted_context` / boundary protocol — there is no mention of an Analysis Engine, Guardian, or IntentFrame's schema or tokens. (For example, the return-agent experiment's Build A system prompt references only developer-controlled `trusted_context` and the customer email thread, never any downstream judge.)

Walk the stages:

| Stage | What must happen | Why it is hard |
|---|---|---|
| **0 — Blind attacker** | The payload author writes into a customer email thread (or similar). | They do not know a judge exists, let alone its two system prompts, its schema, or its per-request random boundary tokens. |
| **1 — Inject the agent** | The thread must manipulate the agent into proposing the malicious action. | Achievable via social engineering (the return-agent experiment showed this). But injecting the agent to misbehave ≠ injecting it to author a working IntentFrame payload — it does not know the target's format. |
| **2 — Agent emits an AE-facing payload** | The agent must submit `reason` / `target` / `data` that carries a second-stage payload for the AE. | That content lands in the AE's **untrusted slot**. Boundary forgery fails (random per-request token). Instruction-like text is supposed to become a flag, not a command. |
| **3 — AE emits a poisoned report** | The AE must produce a misleading `AnalysisReport`. | The AE has **no decision field**, enums are sanitized, and free-text is capped. The best case for the attacker is bounded misleading prose — not direct authorization. |
| **4 — Guardian is also fooled** | The Guardian must return `ALLOW` despite its separate role and policy context. | It must be influenced by content that already survived stages 1–3, while also seeing the raw untrusted fields independently. |

A single payload string would have to be **simultaneously**:

- persuasive enough to manipulate the agent,
- effective as a jailbreak against the AE as a describer,
- and effective as a jailbreak against the Guardian as an enforcer,

while often not knowing two of the three system prompts or the random tokens. Each stage has success probability less than 1, and they largely **multiply**.

In the **white-box** case(see below), the attacker knows IntentFrame exists and may know the open-source prompts. That improves tuning on the semantic frontier (stages 3–4) but does not give structural control over slot placement or the per-request boundary token. The chain still has to complete; white-box knowledge makes the lie sharper, not the architecture disappear.


---

## Binary Answer

Can IntentFrame's AI layer guarantee defense against a white-box, adaptive prompt-injection attacker targeting the agent, AE, and Guardian together?

**No.**

Is there a measured probability for that exact attack?

**No.** The repository has evidence for covered attack categories and transitive-injection experiments, but it does not contain a statistically valid probability for an adaptive white-box attacker with repeated attempts and feedback.

The safe wording is:

> Current tests show strong resistance on covered prompt-injection scenarios, but the exact probability of defense against an adaptive white-box attacker is unknown and should not be stated as a percentage.

---

## The Core Distinction

Prompt injection means attacker-controlled data tries to become instructions.

In a normal agent, the poisoned email, document, web page, or tool output sits in the same context as the agent's actual instructions. The model can be persuaded to treat the attacker's text as higher-priority guidance. If the agent also enforces policy internally, then the same compromised model is both helper and guard.

IntentFrame changes where the guard lives:

- The **agent** talks to users and external content. It is untrusted. It can be prompt-injected.
- The **Analysis Engine** receives the proposed action and describes what it will do. It has no authority to allow or block.
- The **Guardian** evaluates the action against policy and decides `ALLOW` or `BLOCK`.

This is not just prompt hardening. It is separation between the actor being manipulated and the component enforcing the boundary.

---

## Important Correction: IntentFrame Does See Adversarial Text

Do not say "IntentFrame never sees the poisoned source."

In real deployments, the same malicious email thread may be included in `intent.data`. A compromised agent may also fetch a malicious document and place its content in `data`. That content can then be visible to the AE and Guardian.

The accurate claim is:

> IntentFrame may see the adversarial text, but it sees it as untrusted evidence attached to an action proposal, not as operating instructions.

The attacker can write persuasive content into `reason`, `target`, and `data`. They do not get to rewrite the AE's system prompt, the Guardian's system prompt, the policy context, or the runtime boundary markers.

---

## White-Box Attacker: What Changes?

A stronger attacker may know:

- IntentFrame exists in the path.
- The generic AE and Guardian prompts are open source.
- The agent's output will become an IntentFrame request.
- The same email thread may be forwarded into `data`.
- A compromised agent can fetch a second-stage malicious document and include that in `data`.

This makes the attack stronger. It lets the attacker design one payload that tries to:

1. Prompt-inject the agent.
2. Make the agent submit an action that carries a second payload for the AE.
3. Make the AE produce a low-risk or misleading report.
4. Make the Guardian accept that report and return `ALLOW`.

But public prompts do not remove all structure. The boundary protocol does not depend on prompt secrecy. This is Kerckhoffs's principle applied to prompting: the algorithm (the system prompts, the framing scheme) can be fully public, because the only per-request secret is the boundary token. That token is a cryptographically random 128-bit value (`secrets.token_hex(16)`) generated fresh on every request, analogous to a CSRF token. The attacker cannot predict it, cannot forge a matching close marker, and — critically — does not control where the pipeline places their text. Knowing the protocol is not the same as controlling the slot their text lands in.

### Two frontiers: structural vs semantic

It helps to split the white-box attack into two frontiers, because white-box knowledge affects them very differently:

- **Structural frontier** — escape the untrusted slot, override the role, forge a decision token, or overflow the AE -> Guardian channel. White-box knowledge does **not** meaningfully help here. The token is unknown per request, framing is pipeline-controlled, the AE has no decision field, output is fail-closed, and field bounds plus the anomaly flag hold. These defenses do not rely on prompt secrecy, so open-sourcing the prompts does not weaken them.
- **Semantic frontier** — write the most persuasive *plausible lie* that lawfully sits inside the untrusted slot (a fabricated approval record, a lookalike vendor domain, a quiet cover story). White-box knowledge **does** help here, because it lets the attacker tune content to how the models weigh evidence.

So white-box knowledge improves semantic attacks. It does not automatically give the attacker structural control over IntentFrame's prompts. The residual risk shifts almost entirely onto the semantic frontier — which is exactly where the known gaps below live.

---

## Why the Same Payload Has a Harder Job Than It Had Against the Agent

The return-agent experiment showed the core failure mode of agent-only policy enforcement: the agent can be talked into approving and into suppressing its own detection flag. The helper and guard live in the same model.

IntentFrame forces the attack to cross role boundaries.

The same text must be persuasive enough to manipulate the agent but quiet enough not to trip the AE and Guardian. Those goals conflict:

- To manipulate the agent, payloads often use urgency, authority, fake policy, role instructions, or "ignore previous instructions."
- To pass the Guardian, that same instruction-shaped content is evidence of contamination or policy risk.

This is why separating the agent from the judge matters for prompt injection. The judge is not trying to satisfy the user. It is evaluating the agent's proposed action.

---

## The Compounding Chain

Why is injecting the agent, AE, and Guardian **simultaneously** the hard part? Because each stage must succeed for the attack to pay out, and each stage has a different job.

In the simplest case, the agent knows nothing about IntentFrame. Its system prompt only hardens its own generic `trusted_context` / boundary protocol — there is no mention of an Analysis Engine, Guardian, or IntentFrame's schema or tokens. (For example, the return-agent experiment's Build A system prompt references only developer-controlled `trusted_context` and the customer email thread, never any downstream judge.)

Walk the stages:

| Stage | What must happen | Why it is hard |
|---|---|---|
| **0 — Blind attacker** | The payload author writes into a customer email thread (or similar). | They do not know a judge exists, let alone its two system prompts, its schema, or its per-request random boundary tokens. |
| **1 — Inject the agent** | The thread must manipulate the agent into proposing the malicious action. | Achievable via social engineering (the return-agent experiment showed this). But injecting the agent to misbehave ≠ injecting it to author a working IntentFrame payload — it does not know the target's format. |
| **2 — Agent emits an AE-facing payload** | The agent must submit `reason` / `target` / `data` that carries a second-stage payload for the AE. | That content lands in the AE's **untrusted slot**. Boundary forgery fails (random per-request token). Instruction-like text is supposed to become a flag, not a command. |
| **3 — AE emits a poisoned report** | The AE must produce a misleading `AnalysisReport`. | The AE has **no decision field**, enums are sanitized, and free-text is capped. The best case for the attacker is bounded misleading prose — not direct authorization. |
| **4 — Guardian is also fooled** | The Guardian must return `ALLOW` despite its separate role and policy context. | It must be influenced by content that already survived stages 1–3, while also seeing the raw untrusted fields independently. |

A single payload string would have to be **simultaneously**:

- persuasive enough to manipulate the agent,
- effective as a jailbreak against the AE as a describer,
- and effective as a jailbreak against the Guardian as an enforcer,

while often not knowing two of the three system prompts or the random tokens. Each stage has success probability less than 1, and they largely **multiply**.

In the **white-box** case, the attacker knows IntentFrame exists and may know the open-source prompts. That improves tuning on the semantic frontier (stages 3–4) but does not give structural control over slot placement or the per-request boundary token. The chain still has to complete; white-box knowledge makes the lie sharper, not the architecture disappear.

---

## Why the AE Is Not an Authorization Oracle

The Analysis Engine is deliberately limited. It answers: what will this action do?

It does not answer: should this be allowed?

That means injecting the AE is not enough. A poisoned AE can only produce a misleading `AnalysisReport`; it cannot directly approve the action.

The AE output is also structured and bounded:

- It has no `ALLOW` decision field.
- Its typed fields are mapped into enums, with unsafe defaults for unrecognized values.
- Its free-text fields have length and item-count bounds.
- Oversized or malformed AE output can be flagged with `ae_output_anomaly`.

This does not make AE poisoning impossible. It makes AE poisoning a narrow, lossy channel into the Guardian rather than a direct authorization path.

---

## The Real Transitive-Injection Question

The hardest AI-layer question is:

> Can the attacker poison the AE report in a real run, then use that report to poison the Guardian?

The test suite separates two different cases.

First, real end-to-end tests send injected intents through the actual AE and actual Guardian. Those pass in the covered scenarios. This shows that a direct payload in `reason` / `target` / `data` does not automatically become a poisoned report.

Second, the transitive-injection tests hand-fabricate poisoned `AnalysisReport` objects and inject them directly into the Guardian's trusted context. Some of those fail. That is useful evidence, but it means something narrower: if the AE is already fully compromised or bypassed, the Guardian can be influenced by the trusted report it was designed to use.

That is not a reason to claim a vulnerability is impossible. It is the honest boundary:

> The defense against a poisoned AE report mostly lives at the AE boundary. The Guardian is not designed to re-run the entire AE from scratch on every field.

If the Guardian had to distrust every AE claim and re-derive the full semantic analysis itself, the AE/Guardian split would collapse into two duplicated analysis engines.

---

## What the Tests Support

The current evidence supports these claims:

- A single prompt-injected agent is not enough to bypass IntentFrame in the covered tests.
- Direct injection text in `reason`, `target`, or `data` is treated as untrusted input.
- Boundary-forgery attempts remain text inside the untrusted section; they do not become real prompt structure.
- Poisoned AE free-text can reach the Guardian, so transitive injection is a real design concern.
- Real AE -> Guardian tests pass on the covered injection scenarios.
- Hand-crafted fully poisoned AE reports demonstrate residual risk if the AE boundary is assumed already broken.
- More capable Guardian models may be worse at some transitive-injection scenarios because they follow trusted context more faithfully.

The tests do **not** support:

- A claim that prompt injection is impossible.
- A numeric probability for defense against adaptive white-box attack.
- A claim that AE and Guardian are statistically independent in a formal sense.
- A claim that open-source prompts are irrelevant to attack quality.

---

## Probability: What Can Be Said

Do not invent a percentage.

The best honest probability statement is qualitative:

- Against a naive one-shot prompt injection, the defense probability appears high in the covered tests.
- Against a white-box adaptive attacker targeting the agent, AE, and Guardian together, the defense probability is lower and not currently measured.
- Against repeated attempts with feedback, the chance of eventual AI-layer bypass increases unless bounded by non-LLM controls and better policy context.

So the public claim should be:

> IntentFrame makes prompt-injection bypass harder by requiring a chained failure across separate roles and bounded interfaces. Current tests show strong resistance on covered cases, but the system does not claim an AI-layer guarantee or a measured probability against adaptive white-box prompt injection.

---

## When There Is No Deterministic Floor

Not every business policy has a clean deterministic floor.

Some policies can be expressed mechanically:

- maximum amount,
- allowed action type,
- allowed path or recipient,
- blocked command pattern,
- required original payment method.

Those rules can be hard-enforced without relying on an LLM.

But many business policies are semantic:

- Is this really a manufacturing defect?
- Is this refund request contaminated by pressure or fake policy?
- Does this message imply a beneficiary-change scam?
- Is the agent using a document as evidence or obeying it as an instruction?
- Does the stated reason match the real action?

For these cases, IntentFrame's value is not a deterministic proof. The value is that semantic authorization moves out of the compromised agent and into a separate judge with a different role, prompt, context, schema, and incentive structure.

So the guarantee level depends on the policy type:

| Policy type | Example | Enforcement character |
|---|---|---|
| Mechanical policy | "Refund amount must be under $100" | Can be deterministic |
| Semantic policy | "Refund only for manufacturing defects" | AI/context-aware judgment |
| Mixed policy | "Refund under $100 only when defect is credible and payment goes to original method" | Deterministic floor plus AI judgment |

If a business case has no deterministic floor at all, IntentFrame should not be described as providing a hard guarantee. It provides an external semantic authorization boundary that is harder to prompt-inject than the agent itself, but still probabilistic.

For high-risk semantic-only decisions, the honest design choices are:

- add deterministic policy where the business can express it,
- enrich the Guardian with trusted business context,
- require escalation or human approval for low-confidence / high-impact cases,
- log the AE/Guardian evidence trail for audit,
- measure the attack class directly instead of assigning an invented probability.

---

## Why AE / Guardian Separation Still Helps

The split helps even in the white-box case, but it should not be oversold.

It helps because:

- The attacker must defeat two different roles: a factual analyst and a policy enforcer.
- The AE has no authority to authorize.
- The Guardian receives the AE report but also sees the raw proposed action fields.
- The AE -> Guardian channel is structured and bounded.
- Instruction-like content in untrusted fields is supposed to become evidence against the action, not a command to obey.

It is not a proof because:

- Both AI components can still share model-family weaknesses.
- A sufficiently well-crafted semantic lie may be accepted by both.
- A fully compromised or bypassed AE can feed misleading trusted context to the Guardian.
- An adaptive attacker can iterate and tune payloads.

The correct conclusion is:

> Separation changes prompt injection from a single-model failure into a multi-stage chain. It raises the bar and reduces blast radius, but it does not create an LLM-only guarantee.

---

## Fetch-Proxy Attacks

A compromised agent can fetch a malicious document after being injected by the original email thread. The fetched document can then be placed into `intent.data`.

This is in scope. It should not be dismissed.

But the fetched content still enters IntentFrame as agent-supplied data. It is not automatically trusted just because the agent fetched it. It remains in the `reason` / `target` / `data` channel, subject to the same untrusted framing and data-size policy.

This matters because the second-stage document can improve the attacker's payload quality, but it does not give the attacker a direct write path into the AE system prompt, Guardian system prompt, or policy context.

The residual risk is semantic: the second-stage document may contain a quiet, plausible lie that the AI layer misjudges. That is different from structurally escaping the prompt boundary.

---

## Where Prompt Hardening Fits

IntentFrame does use prompt hardening:

- immutable role preambles,
- trusted vs. untrusted sections,
- random per-request boundary tokens,
- normalization,
- closing reinforcement,
- structured outputs.

But prompt hardening is not the main claim.

The main claim is structural separation:

> The agent can be compromised, but it does not get to execute directly or authorize itself. It has to submit an action to a separate judge.

Hardening improves the judge. Separation is why the judge exists outside the compromised agent.

---

## What Not To Claim

Do not claim:

- "IntentFrame cannot be prompt-injected."
- "The AE cannot be poisoned."
- "The Guardian cannot be fooled."
- "Open-source prompts do not matter."
- "The same malicious thread is never passed to IntentFrame."
- "The AI layer provides a mathematical guarantee."
- "We know the probability of defense against adaptive white-box attack."
- "Every business policy has a deterministic floor."

Do claim:

- "Agent prompt injection is assumed."
- "Agent-supplied text reaches IntentFrame as untrusted evidence, not as instructions."
- "A successful AI-layer bypass requires a chained failure across agent, AE, and Guardian."
- "The AE cannot authorize; the Guardian decides."
- "The AE -> Guardian handoff is structured and bounded, but not risk-free."
- "The structural defenses do not depend on prompt secrecy; the only per-request secret is a random boundary token."
- "Where deterministic floors exist, they provide a stronger guarantee than the AI layer."
- "Where deterministic floors do not exist, IntentFrame is an external semantic judge, not a proof system."
- "The current evidence supports strong resistance on covered tests, not a universal guarantee."

---

## Supporting Evidence

The core evidence lives in:

- `external_agents/return_agent/`: shows the agent-only failure mode, where a hardened DIY agent can approve a contaminated request and suppress its own injection flag.
- `docs/business/b2b/techincal_product_engineering/structural_separation_vs_prompt_hardening.md`: explains the helper-vs-guard conflict and why external judging matters.
- `tests/test_transitive_injection.py`: deterministic tests for prompt zoning, boundary forgery, schema bounds, enum sanitization, and AE-output anomaly handling.
- `demo/tests/test_transitive_injection_live.py`: live tests for real AE -> Guardian injection paths and hand-crafted poisoned AE reports.
- `demo/tests/README.md`: explains what the transitive-injection pass/fail counts prove and what they do not prove.
- `docs/threat-model.md`: states the structural prompt-injection defense stack and the explicit non-claim of a formal probability bound.

---

## Short Version

IntentFrame does not solve prompt injection by pretending agents cannot be manipulated. It assumes they can be.

The security move is to move authorization outside the agent and split IntentFrame's AI work into analysis and enforcement. A malicious thread may reach the AE and Guardian, but it arrives as untrusted action evidence, not as the system prompt. To bypass the AI layer, an attacker must first manipulate the agent, then cause the AE to produce a misleading report, then cause the Guardian to allow the action despite its separate role and policy context.

That chain is much harder than prompt-injecting a single DIY agent. It is not impossible. Current tests show strong resistance on covered scenarios, including real AE -> Guardian injection flows, but there is no measured probability or guarantee for an adaptive white-box attacker targeting all components together.