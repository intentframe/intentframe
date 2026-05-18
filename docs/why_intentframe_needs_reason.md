# Why an Intent Frame Carries a `reason` Field

**`reason`** is the sentence that says why the agent thinks this action belongs in the user's task.

IntentFrame does not trust that sentence. A confused or compromised agent can write a misleading reason. But making the agent state a reason still gives the system something valuable: a purpose to compare against the action, a purpose for policies to evaluate, and a purpose for operators to search, review, and audit later.

Without `reason`, an agent trace is mostly a stream of mechanical events: tool names, targets, parameters, results. With `reason`, each event also carries the agent's stated purpose. That does not make the action safe by itself, but it makes governance, review, and observability possible at the level humans actually care about: not just *what happened*, but *why the agent claimed it was happening*.

Function calls, RPC methods, API requests, shell invocations, and tool calls all share one assumption: the caller is a deterministic piece of software whose purpose is fixed at integration time. Permission systems built around them — IAM, RBAC, ACLs, capability tokens — therefore only need to answer one question: *is this caller allowed to perform this action with these parameters?*

An autonomous agent breaks that assumption. The caller is non-deterministic, decides its own actions in response to fluid context, and is itself the component most likely to be confused, hallucinating, misaligned, or under adversarial influence. Granting parameter-only access to such a caller collapses two things that traditional APIs treat as the same: the *mechanics* of an action and the *purpose* under which it was chosen.

The `reason` field is the place where the caller must commit, in plain language, to a purpose for each action it dispatches. It is the smallest declaration that the agent owns and that surrounding evaluators can read alongside the mechanical payload.

The field is not trusted. It is treated as untrusted input throughout the pipeline. Its value lies in what becomes possible once a purpose has been declared at all.

## 1. Policies can be written in terms of purpose

A permission system without `reason` can only express rules over mechanical predicates: action type, target identifier, parameter shape, magnitude, frequency.

A purpose-aware policy expresses the rules humans actually have in mind:

- *"Outbound transfers are allowed only when the requested task explicitly involves that destination."*
- *"Persistent background jobs are allowed only when they are clearly named and tied to maintenance."*
- *"External communication is allowed only when its purpose is consistent with the user's request."*

These rules cannot be evaluated from an action surface alone. The same mechanical action — a network write, a service registration, an email send — is appropriate under some purposes and inappropriate under others. Without `reason`, such policies collapse into two unhelpful options:

- Forbid the action class outright, over-blocking legitimate work
- Permit the action class outright, under-blocking work that is benign-looking but off-purpose

The `reason` field is what lets a policy author write a rule that distinguishes *on-purpose* from *off-purpose* uses of the same action.

## 2. Evaluators gain a stated model to compare against the inferred model

A security evaluator that reads only the action mechanics has a single signal: *what will this do?* It cannot ask the second question human reviewers always ask: *is the actor's framing of this action consistent with what it is about to cause?*

The `reason` field gives the evaluator a second model: a *stated* model of the action, separate from the *inferred* model derived from parameters. Whenever the two disagree, the disagreement is itself a signal — independent of whether either model is sufficient on its own. This is the principle behind double-entry systems: neither column has to be trusted for the comparison between columns to be informative.

The point is not that the agent will reliably tell the truth. The point is that asking the agent to commit to a position creates a comparison surface that did not exist before. An evaluator can act on the comparison even when it could not act on either side alone.

## 3. Observability and audit become tractable at scale

When every action carries a one-sentence stated purpose, agent behaviour becomes legible without digging through parameter dumps or per-tool implementations. This is the day-to-day value operators actually feel.

- **Triage at a glance.** An operator scanning a queue of thousands of daily actions reads `reason` strings, not action arguments. *"Reply to customer about appointment"* / *"Refund order #4827"* / *"Send weekly report"* reads in seconds. Reconstructing the same picture from raw parameters takes minutes per row and does not scale beyond a small team.

- **Search and aggregate by purpose.** You can filter, group, and count actions by what the agent claimed it was doing — *"how often does this agent say it is 'verifying'?"*, *"every action this week where the purpose mentions a customer reply"*. Without a structural purpose field, the same questions require brittle extraction heuristics over heterogeneous parameter shapes.

- **Drift and regression detection.** The distribution of `reason` strings produced by an agent is a stable behavioural signature. If the mix changes — new clusters appear, expected clusters shrink, vague phrasings replace specific ones — something has shifted: a prompt edit, a model swap, a silent role change, an upstream regression. Detecting drift from raw tool calls is harder, because parameter distributions can stay stable while purpose drifts underneath them.

- **Incident reconstruction with intent.** Post-incident, the question is always *"why did the agent do this?"* A record that pairs the action with the agent's stated purpose, the system's inferred effect, and the resulting decision answers it directly. A record of only the action and the decision forces detective work that often cannot be completed days later.

- **Cohort and cost attribution.** Reasons cluster naturally — *"email-confirmation"*, *"data-lookup"*, *"calendar-update"*. Once actions can be labeled by purpose, latency, spend, block rates, and user corrections can be attributed to *purposes* rather than to raw tool types. This is the level at which operators reason about whether an agent is doing the right work, not just whether it is invoking the right APIs.

- **Compliance and review.** Regulatory frameworks for AI-driven systems increasingly require per-action intent records, not per-action invocation logs. Approval workflows, sampled reviews, and audit responses all need a short purpose statement next to each action. The `reason` field aligns the trace with the language those frameworks and reviewers use.

- **Onboarding.** A new operator dropped into a dashboard understands an agent's behaviour by reading reasons. They do not have to learn the parameter schema of every tool first.

This is more than "log a freeform string at the call site." The properties that make it work are structural:

- It is **mandatory** — the SDK refuses to dispatch without it, so coverage is 100% and does not drop out under load, refactors, or stress.
- It is captured **at the intent-declaration site**, reflecting what the agent claims it is doing — not what the tool implementation later wrote about itself.
- It is **co-located with the decision record**, so the audit row already carries the agent's stated purpose, the policy that applied, and the verdict together. Reassembling that picture from scattered per-tool logs is the kind of work most teams quietly never do.

## 4. The agent is required to articulate before acting

Tool-calling agents that emit only mechanical parameters face no obligation to articulate purpose at the moment of action. Models will skip this step when it is not requested. Requiring `reason` adds a small, structural commitment step into every action: the agent must produce a sentence describing the purpose it believes it is acting under, immediately before dispatch.

This is not a guarantee of honesty. It is a guarantee of *articulation*. Articulation is the precondition for everything in the previous three sections — policies keyed on purpose, evaluators that compare stated against inferred, audits and dashboards that record intent alongside effect, reviewers who can scan intent before approving.

## Who consumes the field

Within a layered governance pipeline, the field is consumed differently by different components:

- A **semantic evaluator** uses `reason` to compute the gap between what the agent claims it is doing and what the action will actually cause. The gap is the report; the decision is left to the next layer.
- A **policy decision component** uses `reason` to evaluate purpose-keyed rules — the natural-language limits humans actually write. It also reads the evaluator's report, so it does not depend on `reason` being honest.
- An **executor** records `reason` in the audit trail without acting on it. The field's role at the execution boundary is accountability and forensics, not control.

Of these consumers, the policy decision component is the one whose primary surface degrades most without `reason`: many purpose-keyed rules become unwritable. The semantic evaluator degrades less, because it still has the inferred model to work from — it loses the comparison surface, not its understanding of the action.

## What `reason` is not

The case for `reason` is strongest when stated narrowly. It is worth being explicit about what the field is not.

- It is not a trusted statement of the agent's actual goal. A confused or compromised agent can produce a coherent `reason` that matches a harmful action. Defence against that case depends on independent analysis of the action's effect, not on trust in the field.
- It is not, on its own, a security mechanism. It is a primitive that other layers — policy, semantic evaluation, audit, observability, human review — consume as input. Removed from those layers, the field is cosmetic.
- It is not a substitute for understanding the action itself. Whatever evaluation is needed on the mechanical effect must still be performed. `reason` adds a comparison surface; it does not replace the inspection.
- It is not a substitute for tool-level logging. Knowing the agent claimed *"sending appointment confirmation"* is not the same as knowing the recipient, body, and attachment. Observability is layered: purpose at the top, parameters in the middle, side-effects at the bottom.

## Summary

Autonomous-agent governance has to operate one level above per-call permission systems. Purposes, not just mechanics, are what people, policies, regulators, and operators care about. Without a structural place for an agent to declare a purpose, none of the surrounding machinery can be built: policies keyed on purpose become inexpressible, evaluators have no claim to compare against, audits record events without intent, observability collapses to parameter archaeology, and reviewers see actions without context.

`reason` is the field that makes those layers possible. Its value is in *enabling them to exist*, not in being trusted itself.