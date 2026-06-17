# Jarvis PA

A standalone macOS personal assistant that runs in your terminal. You talk to it, it does things on your Mac.

Jarvis reasons via LLM, manages its own memory and skills, runs proactive background checks, delegates to sub-agents when needed, and handles everything from email to git to calendar — all through natural conversation.

## What this is

Jarvis is a **normal Python application**. It is its own project with its own config, its own data directory (`~/.jarvis/`), and its own identity. It doesn't live inside any framework.

The only external dependency worth noting is the **IntentFrame Actor SDK** (`intentframe-actor` on [PyPI](https://pypi.org/project/intentframe-actor/)) — a small library that Jarvis calls when it needs to touch the real world (read a file, send an email, run a command). In this repo Jarvis is a workspace member installed via `uv sync`; external projects can `pip install intentframe-actor==0.1.0` — see [`docs/package-consumers.md`](../docs/package-consumers.md).

```
You type a message
    → Jarvis (LLM reasoning)
        → actor.submit(action)    ← just a function call
            → IntentFrame evaluates & executes
        ← result
    → Jarvis responds
```

IntentFrame is a dependency, not an identity. Jarvis stores nothing in IntentFrame paths. It follows IntentFrame's security principles (every AI-decided action goes through the pipeline), but architecturally it is decoupled — the same way a Django app follows HTTP semantics without being "an HTTP project".

When the gateway starts Jarvis, it also selects which **action bundles** (`INTENTFRAME_CORE_CONFIG` → `core.yaml`) and **executor packs** (`EXECUTOR_CONFIG` → `jarvis_pa/executor.yaml` or `executor_root.yaml`) load in the supervised stack. See [docs/plugin-profiles.md](../docs/plugin-profiles.md).

## Architecture

```
jarvis/
├── main.py              Entry point, terminal REPL, slash commands
├── agent.py             LLM agent core (OpenAI Agents SDK)
├── tools.py             55+ tool definitions (actor.submit wrappers + memory tools)
├── prompt.py            System prompt builder (Jinja2 templates)
├── config.py            All configuration (model, paths, thresholds)
├── session.py           JSONL conversation persistence + compaction
├── memory.py            Workspace files, auto-capture, memory flush
├── memory_index.py      Hybrid RAG: SQLite FTS5 + sqlite-vec indexer
├── memory_search.py     Search interface: BM25 + vector hybrid scoring
├── skills.py            Discover, gate, index, lazy-load SKILL.md files
├── heartbeat.py         Periodic proactive check runner + notifications
├── state.py             GatedJarvis concurrency gate (single-client access)
├── types.py             Shared dataclasses (AgentContext, SearchResult, etc.)
├── server/              HTTP API server (see jarvis/server/README.md)
│   ├── app.py           FastAPI application + lifespan + entry point
│   ├── routes.py        HTTP/WS route handlers
│   ├── schemas.py       Pydantic request/response models
│   └── events.py        EventBus pub/sub for WebSocket push
├── workspace/           Bundled templates (copied to ~/.jarvis/ on first run)
├── prompts/             Jinja2 system prompt templates
└── skills/              Bundled skill definitions
```

Runtime data lives at `~/.jarvis/`:

```
~/.jarvis/
├── workspace/
│   ├── SOUL.md            Jarvis personality and tone
│   ├── USER.md            User profile and preferences
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
│   └── heartbeat/         Dedup cache (diskcache, 24h TTL)
└── config.yaml            User configuration overrides
```

## Key subsystems

**Memory** — Jarvis remembers things. Workspace markdown files (`SOUL.md`, `USER.md`, `MEMORY.md`) are injected into the system prompt. A daily log auto-captures notable facts from conversation. A hybrid RAG index (BM25 + vector) lets the LLM search past context.

**Skills** — Markdown files with YAML frontmatter that teach Jarvis how to use specific tools (`gh`, `brew`, `docker`, `osascript`, etc.). Skills are gated at runtime — if `gh` isn't installed, the GitHub skill doesn't load. Users can add their own.

**Heartbeat** — A background loop that periodically reads `HEARTBEAT.md`, evaluates the checks via LLM, and sends a macOS notification if something needs attention. Stays silent otherwise. Alerts are deduplicated via diskcache with a 24h TTL.

**Session** — Conversation history persisted as JSONL. When the context window fills up, old messages are summarised and notable facts are flushed to long-term memory before being dropped.

**Sub-agents** — The main agent can spawn lightweight sub-agents for focused tasks. They share the same tools but get minimal context and can't nest further.

**API Server** — A FastAPI server that wraps Jarvis over HTTP (UDS or TCP) so any local client — Telegram bot, dashboard, CLI — can talk to it. Enforces single-client concurrency with a gate. See [`jarvis/server/README.md`](jarvis/server/README.md) for full docs.

**Filesystem tools** — Jarvis exposes only the host-file family
(`read_host_file`, `write_host_file`, `list_host_directory`,
`delete_host_file`) so paths the user sees on disk (`~/Documents/...`)
are the same ones the LLM reasons about. IntentFrame also supports a
virtual-filesystem family for agents that need path isolation; a
background on when each fits lives in
[`../docs/vfs-vs-host-tools.md`](../docs/vfs-vs-host-tools.md).

**Terminal commands** — Jarvis's default gateway policy keeps command and
script work on bash/shell commands, POSIX utilities, and Python. POSIX tools
such as `grep`, `sed`, `awk`, `cut`, `sort`, `find`, `tr`, `head`, `tail`,
and `wc` are part of the supported shell surface. Other language runtimes
such as Node, Ruby, Perl, PHP, Java, Go, Lua, R, Julia, Swift, and Deno/Bun
are outside that surface and are denied by command capability policy before
execution.

`run_command` tool results keep the historic `content` field for stdout and
also include `stderr` on success or failure. This lets Jarvis explain cases
where a shell pipeline exits successfully but an earlier stage wrote an error
to stderr, without changing the output field the model already reads.

**Web search** — handled by OpenAI's hosted `WebSearchTool` (Responses API),
not an IntentFrame actor action. This means web searches bypass the
guardian pipeline and don't appear in the intent audit trail. Fetching
the full content of a specific URL (`get_page_content`) *does* go
through the actor.

## Setup

From the workspace root:

```bash
uv sync
```

This installs Jarvis along with all other workspace members. Requires a running IntentFrame supervisor (provides the security and execution layer).

## Email and account discovery

Email tools in Jarvis (`read_email`, `search_email`, `send_email` in `jarvis/tools.py`) take a required **`account_email`** argument. The model must know that address (from the user, from memory, or from a prior tool result) before it can call those tools successfully.

On the **executor** side, the macOS mail adapter (`intentframe_native_kit/intentframe_executor_pack_macos/adapters/mail.py`) uses EDI’s `EmailClient.get_active_accounts()` to validate `account_email`. If an account-scoped action is submitted **without** `account_email`, the adapter returns **failure** and the error string includes the list of **active** accounts. That is account discovery on the **error path only** — not a separate successful action and not exposed as structured JSON the way `list_calendars` is for calendars.

There is no `LIST_EMAIL_ACCOUNTS` entry in the shared action registry today, and no dedicated Jarvis tool that lists accounts as a normal success response. Until that exists (or `account_email` becomes optional at the Jarvis tool layer with a documented retry flow), assistants may still ask you for an address even though the executor could surface candidates when the field is omitted.

See `jarvis/skills/apple-mail/SKILL.md` and the “Discovering available accounts” section in `external_data_ingestion/README.md`.

## Usage

### Terminal REPL

```bash
jarvis
```

This opens an interactive REPL. Type naturally or use slash commands:

```
/help       Show available commands
/new        Start a new session
/memory     Show memory status
/skills     List active skills
/heartbeat  Run a heartbeat check now
/config     Show current config
/quit       Exit
```

### Server-backed CLI client

```bash
jarvis-cli-client
```

This starts the chat-style CLI client that talks to the Jarvis API server over UDS.

- If `jarvis-server` is already running, the client connects to it.
- If the server is not running, the client starts it automatically and waits until it is ready.
- `Ctrl+C` exits the client and stops the `jarvis-server` process only if this client started it.

Use this when you want the terminal experience to go through the same server API used by other local clients.

### API server

```bash
# UDS (default — what the supervisor and local clients use)
jarvis-server

# TCP (for development/testing)
jarvis-server --tcp
```

See [`jarvis/server/README.md`](jarvis/server/README.md) for endpoints, request/response schemas, error handling, and the concurrency gate design.

## Testing

### Unit tests

Fast, hermetic tests that need no running server, no API key, and no IntentFrame gateway.
Run from the workspace root:

```bash
uv run pytest tests/test_jarvis_memory_get.py    # memory_get path-confinement and line-slice logic
uv run pytest tests/test_host_files_adapter.py   # host-file adapter (PDF, binary, UTF-8, pagination)
```

`tests/test_onboarding_jarvis_policy.py` is a standalone script (not a pytest module) that
drives `AIOnboardingEngine` against a simulated Jarvis policy across all four filesystem-family
modes.  It requires `OPENAI_API_KEY`:

```bash
OPENAI_API_KEY=sk-... python tests/test_onboarding_jarvis_policy.py --fs-mode host
OPENAI_API_KEY=sk-... python tests/test_onboarding_jarvis_policy.py --fs-mode both
```

### Server gate integration tests

The gate tests verify that single-client concurrency enforcement works correctly. They require a running server.

```bash
# 1. Start the server (in one terminal)
jarvis-server --tcp

# 2. Run tests (in another terminal)
python jarvis_pa/test_server_gate.py --tcp
```

For UDS (default transport):

```bash
# 1. Start the server
jarvis-server

# 2. Run tests
python jarvis_pa/test_server_gate.py
```

Flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--tcp` | off | Connect to `127.0.0.1:8100` instead of UDS |
| `--socket PATH` | `/tmp/jarvis.sock` | UDS socket path |

The test suite covers:

- Read-only endpoints (`/health`, `/status`, `/session`)
- Basic `/chat` and `/chat/stream` happy paths
- Concurrent chat rejection (second client gets 429 with first client's identity)
- Read-only endpoints still respond while Jarvis is busy
- 429 response body shape validation
- Stream concurrency (chat-during-stream and stream-on-stream both rejected)
- Cross-type rejection (running `/chat` blocks `/chat/stream` and vice versa)
- Stream disconnect releases the gate for the next caller

## Configuration

All config lives in `JarvisConfig` (`jarvis/config.py`). Values are layered:

1. Defaults in the class
2. `~/.jarvis/config.yaml` overlays by field name
3. `JARVIS_*` environment variables override everything

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `model` | `gpt-5-mini-2025-08-07` | Primary LLM model |
| `sub_agent_model` | `gpt-5-mini-2025-08-07` | Model for sub-agents, summarisation |
| `chat_timeout_seconds` | `600` | Max seconds before gate auto-releases |
| `heartbeat_enabled` | `true` | Enable/disable proactive checks |
| `heartbeat_interval_minutes` | `30` | Minutes between heartbeat checks |
| `context_window_tokens` | `128000` | Context window size for compaction |
