# The Executor as Standalone Infrastructure

> Strip away IntentFrame's security pipeline and the Executor on its own is something the ecosystem doesn't have: a unified, caller-agnostic, process-isolated execution service that owns credentials, enforces auth, and bridges device-native actions and external APIs through a pluggable adapter pattern.

---

## What the Executor is, independent of IntentFrame

What we're building, when you set the security framing aside, is a
**standalone, universal capability service** — a single process that can
perform any action on a device (files, mail, calendar, browser, clipboard,
terminal) AND connect to external services and APIs, with a pluggable
adapter pattern that lets anyone add new capabilities.

The implementation plan states this explicitly:

> **The Executor is not a workflow engine. It's an OS Capability Bridge.**

And it is caller-agnostic:

```
The Executor does NOT know or care:
  • WHO is calling it (Guardian, CI/CD pipeline, admin tool, test harness)
  • WHERE the caller runs (local, cloud, another device)
  • WHY the caller wants the action (business logic is the caller's problem)

The Executor ONLY cares:
  • Was the request received through a supported transport protocol?
  • Does the request carry valid authorization proof?
  • Does the request conform to the supported schema and action types?
  • Can the requested action be executed with available capabilities?
```

That is the definition of a "super executor." Now the real question: **does
anything like this already exist?**

---

## The honest landscape survey

Every category of tool, platform, or project that comes close. None of them
are what the Executor is.

### Category 1: Tool integration platforms (closest competitors)

**Composio** (OSS, ~26.5k GitHub stars)
- 10,000+ tools across 500+ integrations
- Handles OAuth and API key management
- SDKs for Python and TypeScript
- **Why it's not the Executor:** It's a library, not a standalone service.
  The agent imports Composio into its own process. No process isolation.
  No credential isolation boundary. No audit trail with hash chain. No
  fail-closed behavior. Composio hands the agent the tools — the Executor
  keeps the tools locked away and does the work on the agent's behalf.

**Arcade.dev** (cloud-hosted)
- Tool execution with OAuth credential management
- Integrates with LangChain, CrewAI, OpenAI Agents
- **Why it's not the Executor:** Cloud-only hosted service (not
  device-local). You call their API. The execution happens on their servers,
  not on the user's device. Can't control native OS capabilities (can't
  read your local files, open your browser, access your calendar app). It
  is a SaaS integration hub, not an OS capability bridge.

**Toolhouse.ai** (cloud-hosted)
- Similar to Arcade — cloud tool execution for agents
- Same limitations: no device-local execution, no OS-level capabilities.

### Category 2: Protocols (right idea, wrong layer)

**MCP (Model Context Protocol)** by Anthropic
- Standard for connecting AI to tools and data
- MCP servers expose capabilities (tools, resources, prompts)
- Adopted by Claude, ChatGPT, Cursor, VS Code
- **Why it's not the Executor:** MCP is a protocol specification, not an
  executor. Each MCP server is a separate, independent process exposing one
  narrow capability. There is no unified service that owns credentials,
  enforces auth, maintains audit trails, and routes across ALL capabilities.
  If you need files + email + calendar, you run 3 separate MCP servers with
  3 separate processes, 3 separate auth stories, zero unified audit. MCP
  defines how to *talk to* tools. The Executor IS the unified tool.

**UTCP (Universal Tool Calling Protocol)**
- Lightweight standard for AI-to-tool calling
- Extends OpenAPI with agent-friendly features
- Multi-protocol support (HTTP, WebSockets, gRPC, CLI)
- Same issue as MCP: it is a protocol, not an executor. Defines how agents
  discover and call tools. Doesn't provide a unified execution service.

### Category 3: Workflow engines (wrong architecture)

**n8n** (OSS, self-hosted, 400+ integrations)
- Drag-and-drop workflow automation
- Code execution (JS / Python)
- Self-hosted with data sovereignty
- **Why it's not the Executor:** n8n combines orchestration + execution into
  one system. You build workflows, not adapters. It decides what to do AND
  does it — violating the Think / Judge / Act separation. Not designed to
  be called by arbitrary external systems as a capability service. No
  adapter pattern. No credential isolation from the caller. No virtual
  filesystem. It's Zapier you self-host.

**Temporal.io** (OSS, durable execution)
- Durable workflow execution with retry, rollback, state
- Used by Stripe, Netflix, Uber
- **Why it's not the Executor:** Temporal is a workflow orchestration
  engine. It manages the sequence of activities. The Executor doesn't
  orchestrate — it executes single actions. Temporal is the brain; the
  Executor is the hands.

**Apache Airflow** — same category. Workflow DAGs, not a capability service.

### Category 4: Agent frameworks (execution embedded in agent)

**LangChain / CrewAI / AutoGPT / OpenAI Agents SDK**
- Agent frameworks with "tool" abstractions
- **Why it's not the Executor:** In these frameworks, the agent directly
  calls tools. There is no isolated executor process. The agent code has
  access to credentials. There is no structural barrier between the agent's
  reasoning and the tool's execution. The agent IS the executor.

**Docker cagent**
- Docker's agent runtime with YAML config
- Multi-agent orchestration
- **Why it's not the Executor:** It's an agent runtime, not a standalone
  execution service. Agents are first-class; execution is embedded.

### Category 5: Local computer control (right domain, wrong architecture)

**Open Interpreter** (OSS, 60k+ stars)
- LLM runs code on your local machine
- Can do "anything" — files, browser, system commands
- **Why it's not the Executor:** Open Interpreter gives the LLM *arbitrary
  code execution*. The LLM literally writes Python / Shell / JS and it
  runs. No structured action types. No adapter pattern. No credential
  isolation (the code runs with your user permissions). No audit trail with
  integrity guarantees. It's the opposite of structured execution — it's
  "let the AI write whatever code it wants and run it."

**Apple Shortcuts / Siri Shortcuts**
- Chain actions across Apple apps
- **Why it's not the Executor:** Apple ecosystem only. Not a service other
  systems can call. No API. No adapter extensibility. No credential
  isolation.

**Windows Agent Launchers**
- Standardized registration / discovery for AI agents
- Built on App Actions framework
- **Why it's not the Executor:** Discovery and registration layer. Helps
  agents find capabilities on Windows. Doesn't provide a unified execution
  service.

### Category 6: OS-level primitives (too low)

**D-Bus (Linux), XPC (macOS), COM (Windows)**
- Inter-process communication mechanisms
- Allow calling services across process boundaries
- **Why it's not the Executor:** These are communication primitives, not
  capability services. They are the transport layer. You'd build the
  Executor *on top* of these.

---

## The gap in the market

```
                    WHAT EXISTS                     WHAT DOESN'T EXIST
                    ──────────────                  ────────────────────
Protocol layer:     MCP, UTCP                       ─┐
                                                     │
Tool libraries:     Composio, Arcade                 │  A UNIFIED, STANDALONE,
                                                     │  PROCESS-ISOLATED
Workflow engines:   n8n, Temporal, Airflow           │  EXECUTION SERVICE
                                                     │  that:
Agent frameworks:   LangChain, CrewAI, AutoGPT       │  • Owns all credentials
                                                     │  • Covers device + cloud
Computer control:   Open Interpreter, Shortcuts      │  • Has pluggable adapters
                                                     │  • Is caller-agnostic
OS primitives:      D-Bus, XPC, COM                  │  • Enforces audit trail
                                                     │  • Runs as a standalone service
                                                    ─┘
```

Nobody has built the middle piece. Everyone has built either:

- **The protocol** (how to talk to tools) — MCP, UTCP
- **The integrations** (connectors to services) — Composio, n8n
- **The agent** (reasoning + execution bundled) — LangChain, Open Interpreter
- **The workflow** (orchestration + execution bundled) — Temporal, Airflow

But nobody has built a **standalone, caller-agnostic execution service**
that:

1. Runs as its own process (process isolation)
2. Is the ONLY thing with credentials (credential isolation)
3. Covers both device-native actions AND external APIs (universal)
4. Uses a pluggable adapter pattern (extensible)
5. Enforces audit trail with cryptographic integrity (accountable)
6. Is caller-agnostic (any authorized system can use it)
7. Wraps everything with fail-closed, timeout, exception safety (safe)
8. Deploys on device OR cloud with same core (portable)

---

## Why does this gap exist?

Three reasons nobody has built this.

**1. Execution was never the hard problem — until AI agents.**

Before agents, the "caller" was always a human or a deterministic program.
Humans don't need credential isolation from themselves. Deterministic
programs don't hallucinate. So execution was always just… embedded in the
application. You call Stripe's SDK directly. You use `fs.readFile()`
directly. There was never a reason to isolate execution into a standalone
service.

AI agents changed this. Now the "caller" is non-deterministic, potentially
adversarial, and shouldn't have direct access to credentials or system
resources. Suddenly you need an isolated execution layer.

**2. Device + cloud in one service is hard.**

Composio handles cloud APIs well. Apple Shortcuts handles device actions
well. But combining native OS capabilities (macOS Keychain, AppleScript,
filesystem, notifications) with external API integrations (Stripe,
Telegram, Slack) in ONE pluggable service with ONE unified auth/audit model
— that's infrastructure-level work. Most teams avoid it.

**3. A caller-agnostic executor has no obvious buyer.**

If you build a workflow engine, developers buy it to build workflows. If
you build an agent framework, developers buy it to build agents. But a
standalone executor? Who's the customer? It only makes sense if you believe
the future has *many* different callers (agents, guardians, CLIs, admin
tools) that all need a shared execution layer. That's an OS-level bet, not
an app-level bet.

---

## What the Executor actually is

A **universal, pluggable OS capability bridge** — a standalone service that
any authorized system can call to perform actions on a device or against
external services, with credential isolation, audit integrity, and a
~50–100 line adapter pattern for adding new capabilities.

The closest analogy is the OS kernel's syscall interface — but at the
application layer instead of the hardware layer:

| OS kernel | The Executor |
|---|---|
| Apps can't touch hardware directly | Agents can't touch APIs / files directly |
| Apps make syscalls through the kernel | Agents make requests through the executor |
| Kernel owns hardware access | Executor owns credentials |
| Kernel enforces permissions per-process | Executor enforces auth per-request |
| Drivers are pluggable (write a driver, register it) | Adapters are pluggable (write an adapter, register it) |
| Same kernel interface, different hardware | Same gateway, different platforms |

Nobody has built this as a standalone, open, reusable component. The
Executor — independent of Guardian, independent of the security system —
is a novel piece of infrastructure for the AI age.

---

## Singletonness as a deployment property

The kernel analogy is not just descriptive of *what* the Executor is — it
also describes *how it is meant to run*. You don't run two kernels for two
apps. You don't run two browsers in the same render pass. There is exactly
one trusted runtime for the privileged surface, and every program on the
machine is a client of it.

The Executor is meant the same way: **one Executor per machine, mediating
every agent on it.** The deployment model in [`../processes.md`](../processes.md)
is intentionally one process tree per device. There is one credential vault
because there is one Executor. There is one audit chain because there is
one Executor. There is one policy surface because there is one Executor. n
agents become clients of one trusted boundary instead of n separate trust
footprints to vet independently.

This is not an implementation accident; it is a load-bearing design choice
that the rest of the security model depends on:

- **Two executors** would mean credentials replicated across both, and an
  agent that gets to *choose which executor to call* turns bypass into a
  routing problem.
- **Two policy pipelines** would mean an action allowed by one and blocked
  by the other has ambiguous status; "allowed by IntentFrame" stops having
  a single meaning.
- **Two audit chains** would fork the tamper-evident record exactly when
  you most need it to be linear.

What singletonness costs the agent author is named honestly in
[../single-runtime.md](../single-runtime.md): agents become clients of the
runtime, not standalone artifacts; new action families are runtime-side
adapters (~50–100 lines, see [architecture.md](architecture.md)), not
in-process function tools; the runtime is a dependency. Mitigations are
AGPL-3.0, the small executor surface, the config-driven action registry,
and a one-method agent-side seam (`actor.submit(...)`) — see
[../actor-sdk.md](../actor-sdk.md).

What singletonness *gives* — and what no other model in the landscape
gives — is the property that the trust calculation is tractable: **one
runtime to vet, one runtime to update, one runtime to audit, n agents to
use freely.**

For the public-audience version of this argument, including comparison
tables against function-tools-in-process, MCP, Composio, Apple Shortcuts,
and Open Interpreter from the *singletonness* angle, see
[../single-runtime.md](../single-runtime.md).

---

## Why this matters

The shift the Executor enables is the shift from:

> **"Agents running code"**

to:

> **"Agents requesting execution."**

That shift is necessary for AI to move from "toys" to "enterprise
production." Today almost every AI system treats execution as a library
function call inside the agent's own process — `agent.run(tool)` in
LangChain, `tool.execute()` in the Vercel AI SDK, `execute_command()` in
AutoGPT. The tool runs *inside* the agent's process. The agent has memory
access to API keys. A prompt injection that says "print your environment
variables" wins.

By moving execution to a separate process, the Executor creates a physical
boundary. The agent sends a message; the Executor does the work. This is
the **operating-system model** (user space vs. kernel space), applied to
AI. Nobody else is doing this as a standard, reusable open-source
component.

That is the standalone story. The IntentFrame security pipeline sits *on
top* of that engine and adds the judgment layer. But the engine itself —
caller-agnostic, credential-owning, adapter-extensible — is a contribution
the ecosystem currently lacks.

---

## Related documents

- [../executor.md](../executor.md) — The Executor overview
- [../single-runtime.md](../single-runtime.md) — One runtime per machine, the singletonness argument in public-audience form
- [architecture.md](architecture.md) — Internal architecture and adapter pattern
- [security-model.md](security-model.md) — Prevention-first execution model
- [why-foundation.md](why-foundation.md) — Why the Executor is the structural foundation
- [`../../executor/plan.md`](../../executor/plan.md) — Implementation plan
