# Actor SDK — Bring Your Own Agent

> IntentFrame is **agent-agnostic**. Build with any LLM, any framework, any agent SDK. The only requirement is that tool I/O routes through `intentframe_actor.Actor.submit(...)`.

This is the developer-facing companion to [architecture.md](architecture.md). The architecture doc explains *what the runtime does*; this doc explains *what an agent developer has to do* to use it. The answer is small enough to fit on a postcard, which is the whole point.

For the Actor's source, see [`../intentframe_actor/actor.py`](../intentframe_actor/actor.py). For a complete reference integration, see [`../external_agents/invoice_bot/agent.py`](../external_agents/invoice_bot/agent.py).

## Install (PyPI)

```bash
pip install intentframe-actor==0.1.0 intentframe-client==0.1.0
```

Transitive deps resolve from PyPI. Full consumer guide: [`package-consumers.md`](package-consumers.md). License: **Apache-2.0** ([`licensing.md`](licensing.md)).

---

## What this frees you from

The point of routing tool I/O through one runtime is that **agent developers stop shipping security with every agent.** You focus on the agent. IntentFrame handles the rest.

### Platform Control Model

Two boxes — one for what the platform owns, one for what the developer owns. The line between them does not move.

```
┌──────────────────────────────────────────────────────────┐
│  PLATFORM-CONTROLLED (IntentFrame)                       │
│  • Actor SDK (cryptographically signed releases)         │
│  • Analysis Engine (semantic understanding of actions)   │
│  • Guardian: deterministic gates + AI judgement          │
│  • Executor (the only entity with credentials)           │
│  • All security logic                                    │
│  • All AI prompts and validation rules                   │
│  • Audit, hash chain, sandbox profiles                   │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │ Developers integrate via SDK
                          │ Cannot modify security layers
┌──────────────────────────────────────────────────────────┐
│  THIRD-PARTY DEVELOPER CONTROLS                          │
│  • Agent reasoning / business logic only                 │
│  • Natural-language intent declarations                  │
│  • Extension hooks (context, error handling, UI)         │
│  • NEVER: Security logic, credentials, validation        │
└──────────────────────────────────────────────────────────┘
```

> **Android parallel.** App developers write app logic. Android OS controls the permission system. Developers cannot modify how permissions work.
>
> **IntentFrame.** Agent developers write reasoning. IntentFrame controls Actor / Guardian / Executor. Developers cannot modify the security layers.
>
> **Trust model.** Users trust the platform once, not each individual agent. Like trusting iOS, not each app.

### What Guardian validates (and what it doesn't)

The split is sharper than it sounds. Guardian validates **outcomes**, not implementations.

**Guardian DOES validate:**

| Check | Question |
|---|---|
| **Action effect** | What will *actually* happen to the user's system? |
| **User authority** | Does this user have permission for this effect? |
| **Policy compliance** | Does this violate any user-defined rules? |
| **Contextual integrity** | Does this make sense given what we know? |
| **Anomaly detection** | Is this unusual compared to normal patterns? |

**Guardian DOES NOT validate:**

| Not checked | Why |
|---|---|
| Code syntax | That's the agent developer's job |
| Implementation logic | That's the agent developer's job |
| Algorithm efficiency | That's the agent developer's job |
| Programming best practices | That's the agent developer's job |

**Guardian validates OUTCOMES, not IMPLEMENTATIONS.** Everything between *"the agent decided to act"* and *"the action touches the world"* is the runtime's responsibility. Everything before *"the agent decided to act"* — the prompt, the model, the planning, the code that wraps `actor.submit()` — is yours.

### What your agent does not have to ship

- **Credential handling.** Your agent never holds the user's API keys, OAuth tokens, IMAP passwords, or service-account secrets. Those live with the executor.
- **Authorization logic.** Whether action X is allowed for user Y is computed by the runtime against user-owned policy. Your agent doesn't decide; it asks.
- **Outcome validation.** Will this command actually wipe a disk? Does this email address match the policy? Does this path escape the workspace? The Analysis Engine and Guardian answer these.
- **Audit and tamper-evident logging.** The runtime keeps a SHA-256 hash-chained record of every intent, every decision, every execution. You don't need a logging strategy for security-relevant events; one is provided.
- **Sandboxing for terminal commands and filesystem actions.** The executor wraps risky executions in an OS-level sandbox profile. You don't ship sandbox code in your agent.
- **Prompt-injection containment for the action surface.** Even if your agent is fully prompt-injected, the action it submits is evaluated against policy on its own merits — the injection has to *also* fool an independent Guardian LLM that never saw the malicious prompt.

What your agent *does* keep — and what the runtime explicitly **does not** touch — is in the next two sections. The split is intentional and load-bearing: it's the same split Android makes between "your app" and "the OS."

---

## The contract

IntentFrame makes **one** demand of an agent developer: every action that would touch the user's world — read a file, send an email, run a shell command, hit an API, query a database — must be expressed as a structured `IntentFrame` and submitted through the Actor SDK.

That's it. There is no required base class, no required event loop, no required prompt format, no required model, no required framework. Inside your agent, you keep:

- **Your model.** OpenAI, Anthropic, Gemini, a local Ollama model, anything.
- **Your framework.** OpenAI Agents SDK, LangChain, AutoGen, LlamaIndex, CrewAI, plain function calling, a hand-rolled loop, anything.
- **Your prompt strategy.** System prompt shape, few-shot examples, RAG approach, memory model, planning style — all yours.
- **Your tool decomposition.** What counts as a tool, how arguments are typed, when sub-agents spawn — all yours.
- **Your business logic.** Duplicate detection, retry policy, rate limiting, token budgeting — all yours.

What you give up is exactly one thing: **direct I/O.** Your agent process does not open files, hold credentials, talk to external services, or run shell commands itself. Those things live behind `actor.submit(...)`. That is the whole boundary. Inside it, your agent is as flexible as any agent you've ever written.

---

## The whole API

The Actor SDK is one class, three methods, plus a small types module. You can read the source in 20 minutes — see [`../intentframe_actor/actor.py`](../intentframe_actor/actor.py).

```python
from intentframe_actor import Actor
from intentframe_core.types import AgentCapabilities

actor = Actor(
    agent_id="my_agent",
    user_id="user_001",
    socket_path="~/.intentframe/run/intentframe.sock",  # default
)

# 1. Handshake once at startup. Tell the runtime who you are and what you do.
runtime_ctx = await actor.handshake(AgentCapabilities(
    agent_type="MyAgent",
    description="What this agent does, in one sentence",
    capabilities=["read_files", "send_email"],
    action_types=["READ_FILE", "SEND_EMAIL"],
))

# runtime_ctx tells your agent what actions are allowed, what
# constraints apply, and which guardrails to surface in its prompt.
# You inject runtime_ctx into your system prompt — IntentFrame
# never sees your prompt, but your agent should know its envelope.

# 2. Submit every action through actor.submit(...).
result = await actor.submit({
    "action": "READ_FILE",
    "target": "/invoices/oct.pdf",
    "reason": "Extracting vendor and amount for expense tracker",
})

if result.success:
    handle(result.data)
else:
    handle_block(result.error)

# 3. Close when done.
await actor.close()
```

The four fields in the request dict — `action`, `target`, `data`, `reason` — are the entire IntentFrame surface. Anything you put in `data` (or as flat extra keys) is forwarded to the executor as adapter parameters. The `reason` field is what the agent itself believes about why this action is needed; the Analysis Engine compares it against what the action would *actually* do, and the Guardian uses both when it decides.

That's the SDK. There is genuinely no more.

---

## What `submit()` does behind the scenes

You call one function. Inside the runtime, that one function expands into the full pipeline:

```
your tool function
        │
        │   actor.submit({"action": "READ_FILE", ...})
        ▼
Actor SDK (your process)
  • parse request dict → IntentFrame (action as plain string; no taxonomy check)
  • add metadata + signature
  • POST to the IntentFrame runtime over UDS
        │
        ▼
IntentFrame runtime (separate process)
  • Command Shield (for RUN_COMMAND — AST + capability tagging)
  • Deterministic Guardian (policy check, fast path for safe reads)
  • Analysis Engine (semantic AI: what will this REALLY do?)
  • AI Guardian (policy decision based on analysis + your stored policies)
        │
        ▼
Executor (separate process, the only thing with credentials)
  • adapter for the action family (FileAdapter, MailAdapter, etc.)
  • kernel-enforced sandbox under RUN_COMMAND
  • adapter quick_check() floor as last resort
        │
        ▼
ExecutionResult back to your tool
```

Your code never touches any of those layers. They run in a separate process, they have credentials your agent does not, and they apply the user's policy without consulting your agent. Your agent gets back a typed `ExecutionResult` and decides what to do next.

**Optional author-side validation.** The Actor itself does not import `intentframe_native_kit.action_registry`. Agent authors *may* opt in before calling `actor.submit()` — for example Jarvis runs `_validate_against_registry()` in `jarvis_pa/jarvis/tools.py` to fail fast on unknown actions or malformed critical-domain payloads. That is convenience, not security: the bundle runner re-validates authoritatively server-side regardless.

For the full pipeline reference, see [architecture.md](architecture.md). For what each layer protects against, see [threat-model.md](threat-model.md). For why the executor is where credentials live, see [executor.md](executor.md).

---

## Reference integrations

Two complete agents in this repo, both built on the Actor SDK:

| Agent | Framework | What it does | Where |
|---|---|---|---|
| **Jarvis** | OpenAI Agents SDK | Personal assistant — email, calendar, files, shell, git, ~60 tools, sub-agent delegation, hybrid RAG memory | [`../jarvis_pa/`](../jarvis_pa/) — see [jarvis.md](jarvis.md) |
| **Invoice bot** | OpenAI Agents SDK | Processes a directory of invoice files, deduplicates, asks the user when uncertain, writes to an expense tracker | [`../external_agents/invoice_bot/agent.py`](../external_agents/invoice_bot/agent.py) |

Both follow the same shape:

1. Define the tools the LLM can call (`@function_tool` in OpenAI Agents SDK; the equivalent in any framework).
2. In the body of every tool, call `actor.submit(...)` with a structured intent.
3. Build a system prompt that includes the `runtime_ctx` returned from `handshake()` so the LLM knows its policy envelope.
4. Run the agent loop in your framework of choice.

**Jarvis** additionally imports `intentframe_native_kit.action_registry` in its tool layer for optional pre-flight validation (taxonomy + domain payload slices) before `actor.submit()`. The invoice bot does not — it relies on per-tool Pydantic models and server-side enforcement only. Both patterns are valid; the Actor stays registry-agnostic either way.

You can paste either agent into a new project and replace the framework with LangChain, AutoGen, or a raw OpenAI tool-call loop, and the integration with IntentFrame would not change. The Actor SDK is the only seam.

For a sketch of the same pattern in three different frameworks, see [Patterns by framework](#patterns-by-framework) below.

---

## Patterns by framework

These are illustrative — IntentFrame doesn't ship adapters for any of them. Each is just *"the same `actor.submit(...)` call, wrapped in whatever your framework calls a tool."*

### OpenAI Agents SDK

```python
from agents import function_tool, RunContextWrapper

@function_tool
async def read_file(ctx: RunContextWrapper[AgentContext], path: str, reason: str) -> str:
    result = await ctx.context.actor.submit({
        "action": "READ_FILE",
        "target": path,
        "reason": reason,
    })
    return result.data["content"] if result.success else f"Blocked: {result.error}"
```

### LangChain (BaseTool)

```python
from langchain_core.tools import BaseTool

class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a file. Pass `path` and a `reason`."

    async def _arun(self, path: str, reason: str) -> str:
        result = await self.actor.submit({
            "action": "READ_FILE",
            "target": path,
            "reason": reason,
        })
        return result.data["content"] if result.success else f"Blocked: {result.error}"
```

### Plain OpenAI tool-calls (no framework)

```python
async def dispatch_tool_call(name: str, args: dict, actor: Actor) -> str:
    if name == "read_file":
        result = await actor.submit({
            "action": "READ_FILE",
            "target": args["path"],
            "reason": args["reason"],
        })
        return result.data["content"] if result.success else f"Blocked: {result.error}"
    raise ValueError(f"Unknown tool: {name}")
```

The shape repeats. The agent reasons in the framework's idiom; the *moment* the agent wants to act, the action becomes a structured intent and goes through the boundary.

---

## What the boundary catches even if your agent has a bug

The integration is one-sided in a useful way: even a buggy agent can't punch through the boundary, because the boundary is a different process running different code with different credentials.

If your agent:

- **Hallucinates a wrong path** — Guardian denies based on user policy; no file is read.
- **Composes a malicious shell command from user-supplied text** — Command Shield parses the command, tags it as catastrophic, blocks before the executor sees it.
- **Tries to send an email to a wrong address** — Guardian checks against your policy; if the address is off-policy it's blocked, with a forensic report you can read.
- **Has a prompt injection attack succeed** — the agent will *try* to do something it shouldn't, but `actor.submit(...)` is the only door it has, and the runtime evaluates the action on its own merits, not on the agent's reasoning. The injection has to also fool the Analysis Engine and Guardian, which see the action — not the prompt that produced it.

This is the same property the IntentFrame project pitches to evaluators, viewed from the developer side. You don't have to write defensive code at the agent layer to prevent these. The runtime is *already* defensive on your behalf, against bugs and attacks alike.

---

## What IntentFrame does not do for you

To stay honest about scope:

- **It does not write your agent.** Reasoning, planning, prompt engineering, retries, business logic — all yours.
- **It does not validate code you wrote yourself.** If you write `os.system("rm -rf /")` *directly* in your Python code, IntentFrame never enters the picture. The contract is on AI-decided actions; your own deterministic code is your responsibility, the same way it would be without IntentFrame. See [faq.md § Q4](faq.md#q4-does-this-protect-direct-shellfile-access-outside-intentframe).
- **It does not give you a UI.** Jarvis ships with a CLI / Telegram surface; the Actor SDK does not. If you want a UI, build one (or wrap your agent behind the gateway and reuse Jarvis's plumbing).
- **It does not multi-tenant your agent.** Each `Actor(user_id=...)` is scoped to one user's policies. Multi-tenant runtime is a future direction, not a current claim.
- **It does not isolate your agent's process.** Memory, file descriptors, environment variables in your agent process are yours to manage. IntentFrame protects the *outside* world from what your agent decides to do; it does not protect your agent's internal state from itself.

---

## When you'd use this directly

Three audiences, in increasing order of independence:

1. **Build a tool inside Jarvis.** Easiest. Add a tool function in [`jarvis_pa/jarvis/tools.py`](../jarvis_pa/jarvis/tools.py) following the existing pattern; it'll route through the Actor that Jarvis already creates. You don't need to know the SDK exists.
2. **Build a new agent in this repo.** Drop a directory under `external_agents/` with `manifest.yaml` + `agent.py`. Use `intentframe_actor.Actor` directly. The dashboard discovers your agent and the rest of the gateway flow runs unchanged. The invoice bot is the canonical example.
3. **Build an agent in a separate codebase.** Install the Actor SDK as a dependency, point it at a running IntentFrame socket, handshake, and go. This is the *"IntentFrame as runtime, my agent in my own repo"* path. The runtime doesn't care where your code lives.

---

## Quick answers

| Question | Answer |
|---|---|
| Do I have to use OpenAI? | No. The runtime uses OpenAI for its own AI layers (Analysis Engine, Guardian); your agent can use anything. Local-model support for the runtime itself is on the roadmap. |
| Do I have to use a specific agent framework? | No. Jarvis and the invoice bot use OpenAI Agents SDK because that's what the maintainer reaches for; LangChain / AutoGen / raw loops would all work the same. The integration code is `actor.submit(...)` and nothing else. |
| What if my framework wants to take over the tool execution layer? | That's fine — the Actor SDK runs *inside* the tool body, not at the framework's tool-routing layer. Whatever your framework gives you for "this is the function that runs when the model calls a tool," that's where you put the `actor.submit(...)`. |
| Can I bypass the Actor SDK for performance? | You can — but then IntentFrame doesn't see the action and offers no protection for it. Safe reads (`READ_FILE`, `LIST_DIRECTORY`, etc.) resolve in milliseconds via the deterministic fast-path with no AI call. Consequential writes and novel commands run two small-model calls (Analysis Engine + Guardian), adding ~8–15s at current API response times — acceptable for autonomous background work, noticeable in a tight synchronous loop. See [faq.md § Q5](faq.md#q5-what-is-the-latency-cost). |
| Do I have to define my own actions? | Today, you pick from the action registry the runtime ships with — file ops, shell, email, calendar, contacts, HTTP, SQL, user-IO, and the rest. New action families require runtime-side adapters (see [`dev/action-family-wiring.md`](dev/action-family-wiring.md)). |
| Where does `runtime_ctx` come from? | The runtime's onboarding engine: it reads the user's stored policies, computes the agent's allowed actions and constraints, and returns them as a `RuntimeContext` for your system prompt. The user controls policy; your agent receives the resolved envelope. |
| Can I use this without Jarvis or the gateway? | Yes — the runtime (`intentframe-server`) is a standalone service, not coupled to Jarvis. Jarvis is *one* client of it. Your agent can be another. |

---

## Related documents

- [`../intentframe_actor/actor.py`](../intentframe_actor/actor.py) — Actor SDK source (one class, ~200 lines)
- [`../intentframe_actor/__init__.py`](../intentframe_actor/__init__.py) — Public API surface
- [`../external_agents/invoice_bot/agent.py`](../external_agents/invoice_bot/agent.py) — Reference integration (OpenAI Agents SDK + Actor SDK)
- [`../jarvis_pa/jarvis/tools.py`](../jarvis_pa/jarvis/tools.py) — ~60 tool examples in production use
- [architecture.md](architecture.md) — The full pipeline `submit()` triggers
- [executor.md](executor.md) — Where credentials live (not in your agent)
- [threat-model.md](threat-model.md) — What the boundary protects, what it doesn't
- [faq.md § Q4](faq.md#q4-does-this-protect-direct-shellfile-access-outside-intentframe) — The boundary's scope and the developer-cooperation contract
- [jarvis.md](jarvis.md) — The reference assistant built on this SDK
- [dev/action-family-wiring.md](dev/action-family-wiring.md) — How to add a new action family if your agent needs one
