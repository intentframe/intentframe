# Jarvis — The Reference Personal Assistant

> A real personal assistant built on IntentFrame, used as the daily-driver test bed that proves the runtime can host a non-trivial AI agent end-to-end.

Jarvis is an LLM-powered personal assistant that lives in your terminal. You talk to it, it does things on your Mac — read email, run git, manage your calendar, search your files, run shell commands, write notes, send messages. Every action it takes routes through IntentFrame's pipeline before touching your machine.

Jarvis is bundled in this repo for one reason: it is the artifact we use to prove that the IntentFrame runtime actually works for a real, useful agent — not just a benchmark or a contrived demo. It runs on the same machine the maintainer uses every day. The boundary it tests is the boundary that has to hold.

For implementation details (full architecture, every subsystem, every config knob), see [`../jarvis_pa/README.md`](../jarvis_pa/README.md).

---

## Why Jarvis lives in this repo

There are three reasons IntentFrame ships its own reference assistant instead of pointing at someone else's agent.

**1. Skin in the game.** A lot of "AI safety" projects publish a runtime and never use it on anything that matters. Jarvis is the maintainer's actual personal assistant, running on a real laptop, with real credentials, doing real work. If the boundary leaks, it leaks on the person who built it. That is the only way to know it holds.

**2. The runtime needs a non-trivial client to be credible.** A toy agent that wraps three tool calls cannot exercise the full pipeline. Jarvis exercises every layer — Analysis Engine, Guardian, deterministic gates, command shield, executor, audit chain — across dozens of action families and a continuously-evolving prompt surface. If any layer breaks, Jarvis breaks first.

**3. It is the showcase for the autonomy thesis.** [`autonomy.md`](autonomy.md) makes the abstract case that *delegatable autonomy* is the right goal. Jarvis is the concrete answer to *"so what would that actually feel like?"* — an agent that gets work done autonomously, with no approval popups, because the boundary is structural instead of human-in-the-loop.

---

## What Jarvis can actually do

Jarvis exposes around 60 LLM-callable tools — every one of them routes through IntentFrame's pipeline before touching anything real. The tool count is not the success metric. *"Every tool routes through the same boundary"* is the success metric.

| Surface | What Jarvis can do |
|---|---|
| **Email** | Read, search, list, send, reply, forward — across multiple accounts, via [EDI](email-sync.md) |
| **Calendar / Reminders** | Create, list, search, update, delete events and reminders via the [macOS platform server](macos-platform-server.md) |
| **Contacts / Notes / iMessage** | Search contacts, read and write notes, send and read messages |
| **Files** | Read, write, list, delete files on the host filesystem under policy-allowed paths |
| **Shell** | Run shell commands through the command shield (POSIX utilities, Python, bash) |
| **Git / GitHub** | Commit, branch, push, PR — via `gh` and `git` skills |
| **Web** | Hosted web search (OpenAI Responses API) plus URL fetch through the executor |
| **Memory** | Search its own memory, read its workspace files, capture facts to long-term storage |
| **Self-management** | Spawn focused sub-agents, run heartbeat checks, manage its own session |

The full tool list lives in [`../jarvis_pa/jarvis/tools.py`](../jarvis_pa/jarvis/tools.py). The key point: the agent never touches any of these surfaces directly. Each tool is a thin wrapper around `actor.submit(action)` — the Actor SDK call that hands the action off to IntentFrame for evaluation.

```
You type a message
    → Jarvis (LLM reasoning)
        → actor.submit(action)    ← every tool ends here
            → IntentFrame pipeline (Analysis Engine → Guardian → executor)
        ← result
    → Jarvis responds
```

Jarvis itself is a *normal Python application*. The Actor SDK is a dependency, not an identity. Jarvis follows IntentFrame's security principles (every AI-decided action goes through the pipeline), but architecturally it is decoupled — the same way a Django app uses HTTP without being "an HTTP project."

---

## The five subsystems

Jarvis is bigger than a chatbot. The shape of it matters because it is what the IntentFrame runtime has to host.

**Memory.** Workspace markdown files (`SOUL.md`, `USER.md`, `MEMORY.md`) are injected into the system prompt — Jarvis's personality and long-term knowledge. A daily log auto-captures notable facts from conversation. A hybrid RAG index (BM25 via SQLite FTS5 + vector via `sqlite-vec`) lets the LLM search past context. When the context window fills, old turns are summarised and notable facts are flushed to long-term memory before being dropped.

**Skills.** Markdown files with YAML frontmatter that teach Jarvis how to use specific tools — `gh`, `brew`, `docker`, `osascript`, Apple Mail, and others. Skills are gated at runtime: if the underlying CLI isn't installed, the skill doesn't load. Users can add their own.

**Heartbeat.** A background loop that periodically reads `HEARTBEAT.md`, evaluates the user's defined checks via LLM, and surfaces a macOS notification if something needs attention. Stays silent otherwise. Alerts are deduplicated via `diskcache` with a 24h TTL so the same condition doesn't notify repeatedly.

**HTTP server.** A FastAPI service (`jarvis-server`) that wraps the agent over a Unix domain socket — and optionally TCP for development. Any local client can talk to the server: the bundled CLI, the [Telegram bridge](jarvis-telegram.md), or any future surface. Single-client concurrency is enforced by `GatedJarvis` so two clients don't race on the same agent state.

**Sub-agents.** The main agent can spawn lightweight sub-agents for focused tasks — they share the same tools but get minimal context and can't nest further. This keeps the main session lean while still letting Jarvis decompose complex work.

For the deep version of any of these, see [`../jarvis_pa/README.md`](../jarvis_pa/README.md).

---

## How Jarvis exercises the IntentFrame boundary

The architecturally important property of Jarvis is *what it does not do*.

**Jarvis does not hold credentials.** Email passwords, GitHub tokens, API keys live in the credentials vault. Jarvis cannot read them. Adapters in the executor fetch the credential just-in-time, use it, and never expose it to Jarvis or the LLM context.

**Jarvis does not run shell commands.** The LLM produces a `RUN_COMMAND` intent; the command shield parses it, the deterministic gates check it against policy, the Guardian (sometimes) reviews it, and only then does the executor run it inside a kernel-enforced sandbox.

**Jarvis does not write files outside policy.** Every `WRITE_HOST_FILE` and `READ_HOST_FILE` goes through path-confinement gates and Guardian review for sensitive areas.

**Jarvis does not bypass the boundary even for "trivial" actions.** The fast path exists, but it exists *inside* the runtime — Jarvis still calls `actor.submit(...)` for `READ_FILE`, even though that call resolves in milliseconds without an AI call. There is no "shortcut" code path in Jarvis that touches the disk directly.

This is what makes Jarvis a useful test for IntentFrame: an LLM that genuinely believed it had hands would discover, the moment it tried to use them, that it didn't. Every action is *proposed*, never *performed*.

---

## What Jarvis is *not*

We'd rather underclaim than overclaim, so here's the honest version.

- **Not multi-user.** Jarvis assumes one user. Data lives in `~/.jarvis/` and the server enforces single-client concurrency. There is no multi-tenant isolation, no per-user sessions, no role separation.
- **Not multi-platform.** macOS only by design. The heartbeat uses macOS notifications. The workspace assumes Mac path conventions. The platform server integrations require Apple frameworks. Linux support is a separate, unrelated project.
- **Not test-saturated.** Two test files for ~4K LOC of agent code. The test posture is asymmetric: the IntentFrame runtime that *Jarvis exercises* has 95+ test files, the agent itself does not. That is a deliberate prioritisation — the boundary is what's load-bearing, not the agent — but it should be stated.
- **Not productized.** No installer beyond `uv sync` from a fresh clone. No update channel. No telemetry. No support contract. Jarvis is alpha-quality personal-project software that runs in production *for one person*.
- **Not the only client.** The whole point of the HTTP server is that other clients can talk to Jarvis. The first such client is the Telegram bridge — see [`jarvis-telegram.md`](jarvis-telegram.md).

If you need a polished consumer assistant, this is not it. If you need a demonstration that IntentFrame can host a real AI agent doing real work, this is exactly it.

---

## How Jarvis is exposed

In the supported product flow, Jarvis is **a service managed by the IntentFrame gateway** — not a standalone process the user starts directly. You start the gateway via the interactive CLI, the gateway brings up Jarvis (along with the vault, supervisor, EDI, platform server, and Telegram if configured), and you talk to Jarvis through the CLI REPL or any other gateway-aware frontend.

```bash
uv run intentframe-gateway-cli
```

This starts the gateway as a subprocess (if not already running), waits for health, and drops into a REPL. Inside the REPL you can simply type naturally to chat with Jarvis, or use `chat <message>` explicitly. Other REPL commands are available for status, logs, audit, vault, and service management — see [`../intentframe_cli/README.md`](../intentframe_cli/README.md).

Every frontend — the interactive CLI, a future native app, the Telegram bridge — talks to the gateway over `gateway.sock` and nothing else. The gateway proxies Jarvis-specific endpoints (`/jarvis/chat`, `/jarvis/chat/stream`, `/jarvis/events`) to the Jarvis API server it manages internally.

| Surface | What it is | When you'd use it |
|---|---|---|
| **Gateway REPL** (`intentframe-gateway-cli`) | The supported user-facing path. Starts the whole stack and talks to Jarvis through the gateway. | Daily use. |
| **Telegram bridge** | A managed service the gateway auto-starts when `vault set telegram bot_token` + `env set telegram.allowed_user_id` are configured. | Messaging Jarvis from your phone. See [`jarvis-telegram.md`](jarvis-telegram.md). |
| **Standalone Jarvis modes** (`jarvis`, `jarvis-server`, `jarvis-cli-client`) | Dev-only entry points that talk to Jarvis without the gateway. Bypass gateway-level orchestration, env injection, and credential gating. | Local development of Jarvis itself. Not the path users follow. |

For the gateway's full startup sequence, env-injection layers, and the per-service lifecycle, see [`../intentframe_gateway/README.md`](../intentframe_gateway/README.md). For Jarvis-internal architecture (memory, skills, heartbeat, sub-agents, server endpoints), see [`../jarvis_pa/README.md`](../jarvis_pa/README.md).

---

## Outbound traffic profile

When Jarvis is running, three categories of traffic leave the machine:

| Direction | Endpoint | Why |
|---|---|---|
| OpenAI API | `api.openai.com` | LLM reasoning calls, sub-agent calls, hosted web search, Analysis Engine + Guardian when AI review is needed |
| User's email provider | `imap.*` / `smtp.*` | Email reads and sends, via [EDI](email-sync.md) — not Jarvis itself |
| Whatever URL you tell Jarvis to fetch | The target URL | `get_page_content` issues an HTTP GET through the executor |

There is no IntentFrame analytics endpoint, no "Jarvis cloud," no third-party telemetry. The full outbound traffic catalog (across the whole platform) is in [`privacy.md`](privacy.md).

---

## Where Jarvis stores things

```
~/.jarvis/
├── workspace/
│   ├── SOUL.md            Jarvis personality
│   ├── USER.md            User profile
│   ├── MEMORY.md          Curated long-term knowledge
│   ├── HEARTBEAT.md       Proactive check instructions
│   └── memory/            Daily append-only logs
├── sessions/
│   ├── current.jsonl      Active conversation
│   └── archive/           Archived past sessions
├── skills/                User-installed skills (override bundled)
├── index/
│   └── memory.db          SQLite hybrid search index
├── cache/
│   └── heartbeat/         Dedup cache (24h TTL)
└── config.yaml            User configuration overrides
```

Nothing in `~/.jarvis/` is encrypted at the file level — it relies on FileVault / disk encryption. Credentials are not stored here; they live in the credentials vault. See [`credentials-vault.md`](credentials-vault.md).

---

## Quick answers

| Question | Answer |
|---|---|
| Where does Jarvis run? | Locally, on your Mac. The agent process and the executor are on the same machine. |
| Is Jarvis itself a security component? | No. The boundary is IntentFrame's pipeline. Jarvis is just an LLM client that submits intents through the Actor SDK. |
| Can I disable a tool? | Yes — at the policy layer, not in Jarvis. The runtime policy defaults live in YAML at [`../jarvis_pa/jarvis/policies/jarvis.yaml`](../jarvis_pa/jarvis/policies/jarvis.yaml) (and `jarvis_root.yaml`) and are loaded at gateway startup via `policy_registry.seeds.load_policy_seed`. To customise without editing the package, copy the file you want to override to `~/.intentframe/policies/<agent_id>.yaml` (e.g. `~/.intentframe/policies/jarvis.yaml`), edit it, and restart the gateway — the override wins on next bootstrap. The tool stays callable from Jarvis's side; every disabled invocation is denied at the boundary. A higher-level (CLI / app) policy editor is on the roadmap. |
| What if the LLM goes rogue? | The pipeline catches it. Jarvis cannot run a command, write a file, send an email, or spend money without the action passing the deterministic gates and (where applicable) Guardian review. |
| Why is the agent so chatty about reasoning? | Jarvis's prompt asks it to narrate intent before acting. That gives the Analysis Engine more context for its forensic report and helps you, the user, see *why* the agent decided to do something. |
| Can I run Jarvis without IntentFrame? | No. Every tool calls `actor.submit(...)`. Without the runtime, no action goes anywhere. Jarvis is structurally a *client* of IntentFrame, not a standalone agent framework. |
| Can I use a different LLM? | Today: OpenAI only (`gpt-5-mini` family by default). Local-model support (Ollama, llama.cpp) is on the roadmap. |
| What does it cost? | API tokens. In daily use the maintainer sees cents-to-low-dollars per day depending on how heavy the day is. There is no IntentFrame subscription. |
| How do I try it? | See [`quickstart.md`](quickstart.md). |

---

## Related documents

- [`../jarvis_pa/README.md`](../jarvis_pa/README.md) — Implementation reference: full architecture, every config knob, every test, every subsystem
- [`../jarvis_pa/jarvis/server/README.md`](../jarvis_pa/jarvis/server/README.md) — HTTP API server: routes, schemas, error handling, gate design
- [jarvis-telegram.md](jarvis-telegram.md) — The Telegram bridge that lets you message Jarvis from your phone
- [autonomy.md](autonomy.md) — The thesis Jarvis demonstrates: delegatable autonomy via structural supervision
- [evidence.md](evidence.md) — Test results: the boundary that hosts Jarvis is the same boundary tested in the 100-attack sweep
- [architecture.md](architecture.md) — How an action submitted by Jarvis flows through the pipeline
- [executor.md](executor.md) — What the executor does after Guardian approves a Jarvis-submitted action
- [vfs-vs-host-tools.md](vfs-vs-host-tools.md) — Why Jarvis exposes host-file tools (not VFS tools)
- [email-sync.md](email-sync.md) — The email service Jarvis uses
- [macos-platform-server.md](macos-platform-server.md) — The Swift bridge Jarvis uses for Calendar / Contacts / Reminders / iMessage / Notes / Notifications
- [credentials-vault.md](credentials-vault.md) — Where the credentials Jarvis cannot see are stored
- [privacy.md](privacy.md) — What leaves the machine when Jarvis is running
