# One Runtime per Machine

> IntentFrame is meant to be a *singleton*: one runtime on your machine, mediating every AI agent on it. The same way you have one kernel.

The README opens with the framing — **"Users trust a single runtime, not hundreds of agents."** This doc unpacks what that means as a deployment property, what it asks of agents and the frameworks they're built on, and what it costs.

For the OS-kernel analogy in full, see [`mental-models.md` § 7](mental-models.md#7-the-os-kernel--syscall-interface). For why no equivalent runtime exists today and how IntentFrame compares to MCP, Composio, n8n, LangChain, AutoGPT, Open Interpreter, and Apple Shortcuts, see [`executor/standalone-product.md`](executor/standalone-product.md).

---

## The claim

You don't run two kernels for two apps. You don't run two browsers in the same render pass. There is exactly *one* trusted runtime that mediates the privileged surface, and every program on the machine routes through it.

IntentFrame is meant to be that for AI agents on your device:

- **One credential vault.** Email passwords, API keys, OAuth tokens — one process holds them; nothing else.
- **One executor.** Every action that touches files, networks, shells, calendars, contacts — one process performs it.
- **One pipeline.** Command Shield, Analysis Engine, Guardian — one place where intents are evaluated against policy.
- **One audit chain.** Every allow, every block, every action — one tamper-evident log.
- **One policy surface.** Caps, allowlists, path constraints — one source of truth.

`docs/processes.md` lists the actual processes. The model is intentional: there is one of each, started by the gateway, on every device that runs IntentFrame.

The user-visible consequence: when you have Jarvis running locally, the Telegram bridge running for remote access, the invoice bot running in `external_agents/`, and tomorrow some new agent you've added — they are *not* four security stories that have to be kept in sync. They are four clients of the same security story, and the story is told by the runtime, not by the agents. Your trust footprint is the runtime, not the agent fleet.

The singleton boundary is the **security lane**: one runtime process tree protects one machine/environment. The `intentframe-core` pipeline serializes the full lifecycle of each intent — evaluation, decision, execution, and audit — so each action is judged against a stable environment and recorded in causal order. Executor `worker_pool.max_workers` is only a capacity ceiling inside the executor service; it is not the security boundary and must not be used to justify multiple writers into the same environment.

---

## Why singletonness is load-bearing

Take it apart and the security model collapses.

**Two credential vaults.** Now there are two places a leak could come from, and a compromise of either one is still a breach. *Trust mode reverts to "audit each agent."*

**Two executors.** Now policy has to be replicated across both, and the agent has a choice of which one to call. *Bypass becomes a routing problem.*

**Two pipelines.** Now an action allowed by one and blocked by the other has ambiguous status, and "allowed by IntentFrame" no longer has a single meaning. *The audit chain forks.*

**N agents with their own toolboxes (the status quo).** Each one ships its own credential handling, its own tool surface, its own implicit promises. Vetting them is per-agent. Updates are per-agent. Compromise is per-agent — and *contained to the agent only if the agent itself enforces a boundary*, which the field has shown it doesn't.

Singletonness is what makes the trust calculation tractable: one runtime to vet, one runtime to update, one runtime to audit, n agents to use freely.

---

## What this asks of agents (and the frameworks they're built on)

Exactly one thing: route tool I/O through `actor.submit(...)`. The full integration story is in [`actor-sdk.md`](actor-sdk.md); the short version is that the body of every tool — wherever your framework puts tool implementations — calls one method against the local runtime instead of opening a file or hitting an API directly.

Inside that contract, agents keep everything: model choice, framework choice, prompt strategy, memory model, planning style, tool decomposition, business logic. The boundary is structural, not stylistic. Two agents on the same machine using totally different frameworks share the runtime; they don't share each other's *anything else*.

## What this frees agent developers from

The mirror image of the singletonness ask. Because there is one runtime per machine, **agent developers stop shipping security with every agent.** The Android parallel is exact:

> **App developers write app logic. The OS controls the permission system. Developers cannot modify how permissions work.**
>
> *Agent developers write reasoning. IntentFrame controls Actor / Guardian / Executor. Developers cannot modify the security layers.*

Concretely, things your agent does **not** have to ship: credential handling (the executor holds keys, tokens, passwords), authorization logic (the runtime decides against user-owned policy), validation of outcomes (Guardian validates **outcomes, not implementations**), tamper-evident audit logging (one hash-chained record at the runtime layer), terminal/filesystem sandboxing (executor-side, OS-level), prompt-injection containment for the action surface (the action is evaluated independently of the prompt that produced it).

This is the developer side of *"users trust a single runtime, not hundreds of agents"*: agent authors don't have to *be* trusted on security, because they don't ship security. They ship reasoning. The runtime is the only thing that has to be trusted, audited, updated, and forked.

See [`actor-sdk.md § What this frees you from`](actor-sdk.md#what-this-frees-you-from) for the developer-facing version with the verbatim Platform Control Model diagram and the Guardian-validates / Guardian-doesn't-validate tables. The architectural counterpart — *amputated authority per layer* — is in [`architecture.md § View C — Bounded intelligence per layer`](architecture.md#view-c--bounded-intelligence-per-layer).

---

## What this *trades*

It would be dishonest to pretend the model is free. Two real costs.

**1. Agents become clients of the runtime, not standalone artifacts.**

If your agent needs an action family that the runtime doesn't support yet — a new SaaS API, a new device capability, a new file format — you can't just add a function to your tool list. You add an executor adapter (Python, ~50–100 lines per [`executor/architecture.md`](executor/architecture.md)) and wire it into the action registry per [`dev/action-family-wiring.md`](dev/action-family-wiring.md). It's a small amount of code, but it's *runtime-side* code, not agent-side.

This is the exact contract a kernel makes with user-space. New hardware capabilities mean a new driver, not a new app. The benefit is the same: every program that uses the new capability gets it through the same audited path.

**2. The runtime is a dependency.**

Today, IntentFrame is a single project (this repo) maintaining the runtime. If your agent depends on it, you depend on it. The mitigations:

- **AGPL-3.0** — anyone can fork and maintain the runtime independently of the original maintainer.
- **Small executor surface** — adapters are ~50–100 lines each; the executor core is small enough to fork and audit.
- **Action registry is config-driven** — extending capabilities does not require modifying the executor core.
- **No proprietary lock-in at the agent layer** — the seam is `actor.submit({...dict...})`. Re-pointing your agent at a different IntentFrame fork is a config change, not a rewrite.

The dependency exists. It is not unique to IntentFrame — Composio, MCP servers, Kagent, and any other tool platform create the same shape of dependency. The choice is which dependency to take.

---

## How this compares to the alternatives

| Model | Where execution lives | Credentials live with | Policy lives with | Single source of audit? |
|---|---|---|---|---|
| **Function-tools-in-process** (LangChain, CrewAI, AutoGPT, OpenAI Agents SDK, AutoGen) | Inside the agent's process | The agent | The agent | No — per-agent |
| **MCP servers** (one per capability) | A separate MCP server process per tool | The MCP server | None (protocol layer) | No — per-server |
| **Composio / Arcade.dev** (cloud or library) | The integration platform | The platform | None | Per-platform, off-device |
| **Apple Shortcuts** | Apple's actions runner | Apple | None | Apple-internal |
| **Open Interpreter** | Inside the agent's process, *as arbitrary code* | The agent | None | No |
| **IntentFrame** | One executor on the machine, separate process | One executor | One pipeline | Yes — single hash-chained log |

The closest existing thing is MCP — but MCP is a *protocol*, not a runtime. A device with three MCP servers has three execution surfaces, three credential boundaries, three audit perspectives. IntentFrame is the unified runtime *underneath* what the protocol layer is trying to standardize.

`executor/standalone-product.md` does this comparison in much more depth, including why the gap exists.

---

## Where the field is going

The "single runtime, agents are clients" model is not a contrarian bet. As of mid-2026, several projects are converging on the same shape:

- **OpenClaw ACP Everywhere** (RFC) — *"consolidate all LLM/agent launches behind a single ACP runtime seam."* Five execution paths → one.
- **Kagent (Kubernetes-Native Agent Runtime)** — unifies agent execution across LangChain, CrewAI, Google ADK with agent identity, granular access control, policy enforcement, MCP tool sandboxing.
- **OATS (Open Agent Trust Stack)** — zero-trust agent execution through structural enforcement; allow-list-enforced tool contracts; architecturally isolated policy gate independent from LLM influence.
- **CapSeal** (academic, capability-sealed secret mediation) — credentials never reach the agent process; only narrow scoped capabilities flow through.
- **OpenHands SDK** — native sandboxed execution with model-agnostic multi-LLM routing and security analysis.
- **MCP** — donated to the Linux Foundation by Anthropic in December 2025; the protocol layer that depends on a unified runtime existing.

The thesis underneath all of these is the same: *the agent is the user-space; the runtime is the kernel; the security boundary is structural, not behavioural.* IntentFrame got there with a tighter SDK seam (one method) and a singleton deployment model. The rest of the field is converging on the same destination.

---

## Friction for retrofitting OSS agents

Honestly named, because the user is going to ask.

**For new agents:** the seam is one method (`actor.submit(...)`) and the runtime is a local socket. Latency for safe reads is sub-millisecond. The integration cost is hours, not days. New agents pay near-zero cost.

**For existing OSS agents** (LangChain, CrewAI, AutoGPT, AutoGen, OpenAI Agents SDK, etc.): the migration is *non-trivial but bounded*. Every tool body that currently opens a file, hits an API, or runs a shell command becomes a `actor.submit(...)` call instead. For a 10-tool agent, hours. For a 50-tool agent, days. For something deeply embedded like a complex AutoGPT setup, possibly a week.

That's real cost. Two things make it less painful than it sounds:

1. **The seam is smaller than the alternatives' seams.** Migrating to MCP requires running MCP servers per capability, OAuth flows, transport negotiation, and version handling — all of which IntentFrame avoids. Migrating to Composio or Arcade.dev means moving credentials and execution off-device. The IntentFrame seam is just a dict-shaped function call against a local UDS.
2. **The runtime is stable.** LangChain has shipped three incompatible breaking-change cycles since 2023 (v0.0 → v0.1 → v0.2 → v1.0); production teams have done emergency migrations multiple times. The IntentFrame seam (`Actor.submit`) is the *small* surface — it's designed to outlast framework churn rather than participate in it.

The right way to read the friction: this is a one-time cost equivalent to a major framework upgrade you'd be doing in this ecosystem anyway, in exchange for moving credentials, policy, and audit out of agent code permanently.

---

## Quick answers

| Question | Answer |
|---|---|
| Can I run two IntentFrame instances on one machine? | You can in development (different `~/.intentframe/run/` dirs), but the *deployment model* is one. Splitting it forfeits the singleton properties — credentials, audit, policy all fork. |
| Does this lock me into IntentFrame? | Yes — at the runtime layer. Same shape of lock-in as MCP, Composio, Kagent. AGPL + small executor surface keeps it forkable; the agent-side seam is a one-method dict call, not a framework. |
| What if my agent needs an action that doesn't exist? | Add a runtime-side adapter (~50–100 lines, see [`executor/architecture.md`](executor/architecture.md) and [`dev/action-family-wiring.md`](dev/action-family-wiring.md)). It then becomes available to *every* agent on the machine, not just yours. |
| Is this multi-tenant? | Not today. Today's runtime is scoped to one user. Multi-tenant policy administration is a future direction. |
| Where does this live in the deployment? | One process tree per machine, all under `~/.intentframe/run/`. See [`processes.md`](processes.md). |
| What does this give me that MCP doesn't? | A unified execution layer underneath the protocol — credential isolation, structural prevention, single audit chain, policy across all action families instead of per-server. MCP and IntentFrame are not competitors; MCP is a protocol layer that benefits from a unified runtime existing. |

---

## Related documents

- [autonomy.md](autonomy.md) — the thesis IntentFrame is the runtime for
- [architecture.md](architecture.md) — what runs through the singleton
- [processes.md](processes.md) — the actual process tree per machine
- [mental-models.md § 7](mental-models.md#7-the-os-kernel--syscall-interface) — the OS-kernel analogy in full
- [executor/standalone-product.md](executor/standalone-product.md) — why no equivalent unified runtime exists; comparison to MCP, Composio, n8n, LangChain, AutoGPT, Open Interpreter
- [executor/why-foundation.md](executor/why-foundation.md) — why the executor (not Guardian) is the structural foundation
- [actor-sdk.md](actor-sdk.md) — the developer-facing seam that makes this an integration of one method
- [faq.md § Q12](faq.md#q12-does-this-lock-me-into-intentframe-for-tool-capabilities) — the dependency trade-off, named honestly
