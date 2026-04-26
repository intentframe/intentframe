# Stub-Agent Crash-Test Rationale

## Position

The root demo's primary proof should use a deterministic compromised-agent
harness, not a live prompt-injection attempt against a real LLM.

This is not a concession. It is the correct test shape for IntentFrame's claim.

IntentFrame is a post-compromise runtime control plane. It does not claim that
the model cannot be tricked. It asks what damage can happen after the model,
planner, memory, tool output, or surrounding agent loop has already failed.

The root demo therefore does not test the agent's LLM, model provider, prompt,
refusal behavior, or live jailbreak resistance. Those variables are intentionally
out of scope. The system under test is IntentFrame itself: policy, deterministic
gates, command inspection, and the Analysis Engine / Guardian layers that are
hardened and tested against prompt-injection-style inputs.

## Why Not Require A Real LLM?

A live LLM demo mainly tests whether one prompt can make one model misbehave on
one run.

That is useful for storytelling, but it is weak as a containment proof:

- model providers improve refusal behavior over time;
- behavior changes across model versions, temperatures, and system prompts;
- obvious malicious prompts may be refused before IntentFrame is exercised;
- a failed jailbreak can look like a successful safety system even though the
  runtime boundary was never tested;
- a successful jailbreak can be hard to reproduce later.

For this demo, model refusal is noise. The proof starts after refusal has failed.
The interesting question is not "which model did the agent use?" The interesting
question is "what happens after any agent submits this intent?"

## What The Stub Proves

The stub agent proves that if an authenticated agent submits a dangerous intent,
IntentFrame still evaluates it through the same runtime boundary:

```text
Stub agent
  -> Actor handshake
  -> submit(intent)
  -> policy lookup
  -> command_shield / deterministic gates
  -> Analysis Engine
  -> Guardian
  -> executor only if approved
```

The stub uses the same Actor path that a real LLM-backed agent uses. It is not a
shortcut around the system under test.

In IntentFrame terms, an agent is any program that can authenticate, receive a
policy-bound session, and submit intents. The agent may be an LLM loop, a
workflow engine, a CLI harness, or a deterministic test program. The safety
boundary should not depend on which one produced the intent.

That is why a fixed stub is valid here: it removes the agent model from the
measurement and forces the IntentFrame boundary to handle the submitted action.

## Why This Is Stricter

The deterministic harness is stricter than a live jailbreak demo because it
removes model luck:

- the dangerous intent is always submitted;
- the root executor capability is always preflighted;
- the same attack corpus can be rerun by others;
- failures are attributable to the runtime boundary, not to prompt phrasing;
- success means unauthorized effects were blocked after worst-case agent failure.

This is the same reason crash tests use instrumented test rigs. The rig is not a
fake car. It is a reproducible way to measure what happens after impact.

## How To Present It Honestly

The demo should say this directly:

> This is a compromised-agent crash test. We are not relying on a live model to
> misbehave on camera. We start after the agent has failed and test whether the
> runtime boundary still protects the machine.

The UI can still label the actor as an "agent" if the page makes clear that this
is a deterministic harness. Avoid implying that a live LLM generated each action
unless that is actually what happened.

The skeptic's question is valid:

> Am I watching a live model get tricked, or a deterministic harness submitting
> fixed intents?

The answer should be visible in the demo itself. The crash-test segment should
say "deterministic compromised-agent harness" and show at least one submitted
intent payload. If a live Jarvis segment is included, label it separately as
product feel, not the containment proof.

## Recommended Demo Split

Use two separate segments:

1. **Crash-test proof**: deterministic stub agent submits fixed malicious intents
   against the root-capable profile. This is the primary security proof.
2. **Product feel**: interactive Jarvis runs normal useful root/admin inspection
   commands and shows the operator experience. This is useful context, not the
   containment proof.

Do not mix the claims. The first segment proves containment. The second segment
shows usability.

## What Skeptics May Ask

### "Isn't this just hardcoded JSON?"

Yes, intentionally. The fixture is the impact payload. The question is whether a
malicious intent that reaches the runtime boundary can execute unauthorized
effects. The submitted JSON should be visible and inspectable.

The important claim is not "a live LLM generated this exact JSON." The important
claim is "any agent that submits this intent through the normal Actor path is
contained by the same runtime boundary."

### "Does this prove models are vulnerable?"

No. That is not the claim. Existing prompt-injection research and real incidents
already show that agents can be compromised. This demo assumes compromise and
tests containment.

It also does not compare models or score the agent model's jailbreak resistance.
IntentFrame's own AI layers are separate runtime components with prompt
hardening, structured outputs, deterministic pre-gates, and test coverage for
prompt-injection-style inputs. The root demo evaluates that runtime boundary,
not the agent's chosen LLM.

### "Does this prove every agent is safe?"

No. It proves actions routed through IntentFrame and covered by policy are
evaluated before execution. Direct unmanaged tool access, side channels, and
out-of-bound local shell access remain out of scope.

### "Why show root?"

Root is the stress condition. It makes the consequence obvious: if the boundary
fails, the agent can touch privileged local state. If the boundary holds under
root-capable command execution, the containment story is much easier to
understand.

## Success Standard

The stub-agent demo succeeds when a technical viewer can verify all of this:

- the executor had effective root capability for `RUN_COMMAND`;
- the submitted intents were malicious or unauthorized;
- the intents went through the normal Actor and IntentFrame pipeline;
- useful allowed commands executed;
- blocked commands returned `decision=BLOCK`;
- blocked commands did not execute;
- the result is reproducible without depending on a live model jailbreak.
