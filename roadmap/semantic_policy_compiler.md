# Semantic Policy Compiler Roadmap

## Summary

IntentFrame should eventually support a policy compiler that converts plain
English `intent_limits` into typed deterministic constraints such as
`deny_capabilities`, `blocked_patterns`, and other machine-checkable policy.

The operator-facing source of truth should remain plain English. The compiled
constraints should be cached, inspectable, versioned, and used by
Deterministic Guardian for fast enforcement. The original `intent_limits`
should still flow through Analysis Engine and Guardian as semantic context on
every reviewed intent.

This is a strong v1.1 / v2 product direction. It should not block the initial
public root-demo release.

## The Idea

At startup or policy-change time, IntentFrame would call a policy-compiler LLM:

> Here are the operator's plain English intent limits. Here is the current
> capability taxonomy and typed constraint vocabulary. Generate the deterministic
> constraints that best enforce these limits.

Example operator policy:

> Don't change my network settings, hostname, or time sync.

Possible compiled output:

```yaml
compiled_deny_capabilities:
  - "capability:system_mutate:host_network_config"
  - "capability:system_mutate:hostname"
  - "capability:system_mutate:time_sync"
  - "capability:system_mutate:hosts_file"
```

This compile step happens once per policy version, not per intent. The hot path
remains unchanged:

```text
command_shield
  -> Deterministic Guardian
  -> Analysis Engine when needed
  -> Guardian when needed
  -> Executor only if approved
```

## Why It Adds Value

### Non-technical policy authoring

Today, deterministic enforcement requires knowing technical vocabulary such as
`capability:system_mutate:host_network_config`. A normal operator should not
need to know that. They should be able to write:

> Don't change my network settings.

The compiler translates that into the machine vocabulary the deterministic
layer can enforce.

### Machine-speed enforcement from English

If a plain English rule compiles to typed constraints, many violations can block
in milliseconds without per-intent LLM calls.

This does not replace semantic review. It converts the parts of the English
policy that map cleanly to known surfaces into deterministic gates.

### Lower maintenance burden

The current model can require mirrored deny lists across bootstrap policy,
manual seed policy, and demo policy. A compiler could reduce that burden by
making English policy the operator-facing source, with generated deterministic
constraints derived from it.

### Better auditability than semantic-only enforcement

Compiled constraints are reviewable. A human can inspect the generated output
and ask whether it matches the original intent.

Semantic-only enforcement answers "the model judged this." Compiled policy can
answer "this English limit compiled to these specific deterministic gates."

## Accuracy Impact

### Current layered root demo

Expected impact: **near zero**.

The current root demo already reaches 100/100 on the attack corpus with
manually-authored deterministic constraints. A compiler cannot improve that
number. It would automate how those constraints are produced.

### Semantic-only policy experiment

Expected impact: **potentially meaningful**.

If a semantic-only policy catches 85-90 of 100 attacks, a compiler may lift that
coverage by converting some English limits into deterministic constraints.

The practical value depends on measured semantic-only gaps. The compiler should
be evaluated after the semantic-only root policy experiment, not before.

### Non-technical operator scenario

Expected impact: **high**.

If an operator writes only English `intent_limits`, without understanding
`deny_capabilities`, the compiler can move their effective protection closer to
what a technical policy author would have written manually.

The compiler cannot invent policy. If the operator forgets to say "do not touch
audit logs," the compiler should not silently infer that boundary.

## Latency And Cost Impact

### Per-intent hot path

The compiler does not add per-intent latency. It runs at policy creation,
policy update, or capability-vocabulary update time.

### Deterministic block path

If compiled constraints catch an intent, the system can block at Deterministic
Guardian with no AE or Guardian LLM call.

Typical shape:

```text
deterministic block: milliseconds, 0 LLM calls
semantic review: seconds, usually AE + Guardian LLM calls
```

### Current root demo

Expected impact: **small**.

The current manually-authored `deny_capabilities` list already catches most
root-demo attacks deterministically. A compiler would not materially reduce
latency for this existing proof.

### Production scale

Expected impact: **moderate to high when sensitive violations are frequent**.

If many intents violate English policy and would otherwise reach AE + Guardian,
compiled constraints save LLM calls and reduce latency. If most traffic is
benign and not covered by deny-style English limits, the compiler does not make
those benign intents faster.

## False Positive And False Negative Risk

### Over-blocking

The compiler may interpret English too broadly.

Example:

> Don't change my network settings.

Correct typed constraints:

```yaml
- "capability:system_mutate:host_network_config"
- "capability:system_mutate:hostname"
- "capability:system_mutate:time_sync"
```

Possible over-broad mistake:

```yaml
- "capability:network_probe:dns_lookup"
```

That would block harmless commands like `dig github.com` or a benign API read,
even though the operator meant network configuration, not all network activity.

### Under-blocking

The compiler may miss a relevant tag.

Example:

> Don't disable my security tools.

The compiler might include firewall and EDR tags, but miss audit-log tampering:

```yaml
- "capability:system_mutate:firewall"
- "capability:system_mutate:security_daemon"
```

Missing:

```yaml
- "capability:system_mutate:audit_log"
```

The semantic layer still sees the original English rule, but the deterministic
gate would not catch that missed surface.

### Rough expectation

With well-scoped English and a complete capability vocabulary supplied to the
compiler, first-pass mapping may cover roughly 85-90% of the intended typed
surface. The remaining 10-15% risk is a mix of over-broad tags and missed tags.

This is why compiled output must be reviewable and diffed, not silently trusted.

## Trust Boundary Impact

The policy compiler LLM would become part of the trusted computing base.

This is different from AE and Guardian. AE and Guardian operate inside the
deterministic envelope. The compiler helps write that envelope.

Failure modes:

- It silently omits a tag the operator expected.
- It adds a broad tag that breaks useful workflows.
- It produces different output after model, prompt, or vocabulary changes.
- An operator trusts the compiled output without reviewing it.

The compiler should therefore be treated as a policy-assistant, not an
unreviewed authority.

## Safer Design

### Feed the compiler the known vocabulary

Do not ask the LLM to invent tags. Give it the current capability taxonomy and
allowed typed policy fields.

Instruction shape:

> Only use tags from this list. If the English policy cannot be represented by
> existing typed constraints, say so and leave it to semantic review.

### Make output inspectable and pinned

Compiled output should be stored with metadata:

- source `intent_limit`
- compiler model and prompt version
- capability taxonomy version
- generated constraints
- confidence or uncertainty notes
- timestamp

The system should diff regenerated output against prior output.

### Keep English limits in the semantic path

The compiler must not consume and replace `intent_limits`.

Original English policy should still be sent to AE and Guardian so semantic
review can catch cases the compiler missed.

### Require review before policy changes become active

For early versions, generated constraints should be proposed, not silently
activated.

The operator-facing workflow should be:

1. Operator writes English policy.
2. Compiler proposes typed constraints.
3. Operator or admin reviews the diff.
4. Approved constraints become active.
5. Original English remains active for semantic review.

### Emit a coverage report

The compiler should explain:

- which limits compiled cleanly,
- which tags were selected,
- which tags were considered but not selected,
- which limits remain semantic-only,
- where human review is recommended.

Example:

```text
Limit: "Don't read my passwords or tokens"
Compiled tags:
  - capability:data_read:credential_material
  - capability:data_read:cloud_tokens
  - capability:data_read:password_manager_export
Uncertain related tags:
  - capability:data_read:process_env
  - capability:data_read:shell_history
Recommendation: review before activation.
```

## Recommended Timing

### Do not build before the first public root-demo release

Reasons:

- The current layered root demo already has 100/100 attack containment.
- It adds a new trust boundary that must be tested and documented.
- It complicates the clean public explanation of deterministic vs semantic
  enforcement.
- The semantic-only coverage number has not been measured yet.

### Build after semantic-only evaluation

The right sequence is:

1. Measure semantic-only root policy coverage using plain English
   `intent_limits`.
2. Measure benign false-positive rate under both layered and semantic-only
   policy.
3. Identify where English semantic review missed attacks or over-blocked useful
   work.
4. Use those gaps to justify and design the compiler.
5. Build the compiler as a v1.1 / v2 product feature.

## Expected Product Impact

### Short term

Low impact on the current root-demo numbers. The demo already passes with
manual deterministic policy.

### Medium term

High value for non-technical policy authoring:

> Write policy in English, get inspectable deterministic enforcement where
> possible, and keep semantic review for everything that cannot be reduced to a
> typed gate.

### Long term

This can become the main operator experience:

1. User writes or edits plain English policy.
2. IntentFrame compiles the parts it can enforce deterministically.
3. IntentFrame explains what it compiled and what remains semantic-only.
4. User approves the generated policy.
5. The runtime uses both deterministic constraints and semantic review.

## Verdict

The semantic policy compiler is likely valuable, but mostly as a product and
operator-experience feature, not as a pre-launch demo improvement.

It can improve effective accuracy for English-only operators, reduce LLM calls
for sensitive violations that compile into typed constraints, and make policy
maintenance easier. It also introduces a new trusted component, false-positive
risk, drift risk, and review requirements.

The right posture:

- keep it out of the first public release,
- measure semantic-only policy coverage first,
- build the compiler if the measured gap is significant,
- always keep original `intent_limits` flowing through AE and Guardian,
- never silently trust generated constraints without auditability and review.
