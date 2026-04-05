# Jarvis Telegram Bot — Architecture

> How the Telegram bot process connects your phone to the Jarvis API server running on your Mac.

---

## System overview

```
┌─────────────────────────────────────────────────────────────────┐
│  YOUR MAC                                                       │
│                                                                 │
│  ┌─────────────────────┐     UDS      ┌──────────────────────┐  │
│  │  jarvis-telegram    │─────────────▶│  jarvis-server       │  │
│  │  (this module)      │  POST /chat  │  (FastAPI)           │  │
│  │                     │◀─────────────│                      │  │
│  │  Long-poll loop     │              │  GatedJarvis         │  │
│  │  Event listener     │  WS /events  │  JarvisAgent         │  │
│  │                     │◀─────────────│  EventBus            │  │
│  └────────┬────────────┘              └──────────────────────┘  │
│           │ HTTPS                                               │
└───────────┼─────────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────┐
│  Telegram Bot API     │
│  (cloud)              │
│  getUpdates           │
│  sendMessage          │
│  sendChatAction       │
│  editMessageText      │
└───────────┬───────────┘
            │ MTProto / push
            ▼
┌───────────────────────┐
│  Telegram app         │
│  (your phone)         │
└───────────────────────┘
```

The bot is a **separate process** from the Jarvis server. It is a **pure client** — structurally identical to `jarvis-cli-client`, but using Telegram as the transport instead of a terminal.

---

## What lives where

| Component | Where | Role |
|-----------|-------|------|
| Telegram app | User's phone/desktop | UI + push notifications |
| Telegram Bot API | Telegram's cloud | Message relay (getUpdates, sendMessage, editMessageText) |
| `jarvis-telegram` | Your Mac | Long-polls Telegram; calls Jarvis over UDS; forwards alerts |
| `jarvis-server` | Your Mac | FastAPI over Unix socket: `/chat`, `/health`, `/status`, `/events` |
| `JarvisAgent` | Your Mac (inside server) | LLM loop, session, tools, heartbeat |

---

## Connection to Telegram cloud

The bot connects **outbound** to Telegram's API — no public URL, no webhooks, no inbound ports.

- **Long polling**: repeated `getUpdates` (HTTPS) — Telegram holds the request open until updates arrive or a timeout elapses, then the bot immediately issues the next request.
- **Outbound calls**: `sendMessage`, `sendChatAction`, `editMessageText` (HTTPS) for replies.

The **bot token** (from BotFather) is the only credential. It is passed to `python-telegram-bot`'s `Application.builder().token(...)`.

---

## Connection to Jarvis server

The bot connects to the FastAPI server over a **Unix domain socket** (default `/tmp/jarvis.sock`) using `httpx.AsyncClient` with `AsyncHTTPTransport(uds=...)`.

- **`POST /chat`** — synchronous chat (no streaming). Returns the full response text.
- **`GET /health`** — startup readiness check.
- **`GET /status`** — used by the `/status` command.
- **`WS /events`** — WebSocket for proactive heartbeat alerts.

Read timeout is 660s, matching the server's 600s gate timeout with buffer.

---

## Message lifecycle: user sends text

```
1. User types message in Telegram app
2. Telegram cloud delivers it via getUpdates
3. Bot receives Update
4. Auth check: update.effective_user.id == ALLOWED_USER_ID
5. Bot sends ChatAction.TYPING (read receipt)
6. Bot sends "Thinking…" placeholder message
7. Bot spawns typing keep-alive task (re-sends TYPING every 4s)
8. Bot calls POST /chat on Jarvis server over UDS
9. GatedJarvis acquires gate → JarvisAgent.chat() → gate releases
10. Server returns {"response": "...", "tokens": N}
11. Bot edits "Thinking…" with actual response
    - If response > 4096 chars: split into chunks
      - First chunk edits placeholder
      - Continuation chunks: new messages prefixed "(continued…)"
    - If response > max_response_chars (16K default): truncated with "… (truncated)"
12. Typing keep-alive task is cancelled
```

---

## Message lifecycle: proactive alert

```
1. JarvisAgent heartbeat detects something noteworthy
2. Heartbeat callback publishes to EventBus
3. EventBus fans out to /events WebSocket subscribers
4. Bot's event listener receives JSON frame
5. If type == "heartbeat_alert":
   Bot sends message to user prefixed with "[Alert]"
```

The event listener auto-reconnects on WebSocket disconnect.

---

## Module structure

```
jarvis_telegram/
├── pyproject.toml          # Package metadata, dependencies, entry point
├── README.md               # Setup and usage
├── ARCHITECTURE.md         # This file
└── jarvis_telegram/
    ├── __init__.py
    ├── bot.py              # Application wiring, server wait, event listener, entry point
    ├── handlers.py         # Message handler, command handlers, typing keep-alive
    ├── client.py           # Async httpx client to Jarvis server over UDS
    └── config.py           # TelegramConfig (pydantic-settings, env vars)
```

### `bot.py`

- `build_app()` — wires handlers, shared state (`bot_data`), lifecycle hooks.
- `_post_init()` — validates bot token via `get_me()`, waits for Jarvis server health, starts event listener task.
- `_post_shutdown()` — cancels event task, closes httpx client, logs each step.
- `_event_listener()` — connects to `/events` WebSocket, forwards `heartbeat_alert` events as `[Alert]` messages.
- `main()` — entry point (`jarvis-telegram` console script). Sets up logging, loads config, runs polling.

### `handlers.py`

- `handle_chat()` — auth check, typing indicator, "Thinking…" placeholder, `POST /chat`, edit with response. Handles busy/timeout/server errors.
- `handle_start()` — `/start` welcome message.
- `handle_status()` — `/status` command, calls `GET /status`.
- `handle_help()` — `/help` command, lists commands.
- `_send_response()` — truncation (if over `max_response_chars`), splitting (4096-char Telegram limit), continuation prefixes.
- `_keep_typing()` — re-sends `ChatAction.TYPING` every 4s until stopped.

### `client.py`

- `JarvisClient` — async httpx over UDS. Methods: `chat()`, `status()`, `is_healthy()`, `close()`.
- Typed exceptions: `JarvisBusyError` (429), `JarvisTimeoutError` (504), `JarvisServerError` (5xx).
- `_safe_json()` — graceful JSON parsing for error responses that may not be JSON.

### `config.py`

- `TelegramConfig` — pydantic-settings with `JARVIS_TELEGRAM_*` env prefix.
- Fields: `bot_token`, `allowed_user_id`, `jarvis_socket_path`, `max_response_chars`.

---

## Security

- **Single authorized user**: `JARVIS_TELEGRAM_ALLOWED_USER_ID`. All other users are silently ignored (logged as warning).
- **No public exposure**: long polling is outbound-only. No webhooks, no open ports.
- **Bot token**: the only credential touching the network. Should be stored securely.
- **Jarvis server**: local UDS only. The bot is the bridge between Telegram and Jarvis — Jarvis never talks to the internet directly through this path.

---

## Concurrency

The Jarvis server enforces **one active chat at a time** via `GatedJarvis`. If the bot sends `POST /chat` while the CLI (or another client) is already chatting, the server returns **429** and the bot edits the placeholder to "Jarvis is busy talking to {client}."

The `client` field in the chat request is always `"telegram"`, so other clients see "busy talking to telegram" in their 429 responses.

---

## Future considerations

### Multi-user support

Currently single-user. Two possible evolution paths:

1. **Shared session** — allow multiple `allowed_user_ids`, prefix messages with user identity. Everyone shares one Jarvis session and the concurrency gate. Simplest change.
2. **Independent sessions** — per-user sessions, memory, and gate. Requires changes to `JarvisAgent` (multi-tenant), not just the bot.

### Tool call visibility

The bot uses `POST /chat` (final text only). Tool calls are not visible in Telegram. To show them, the bot would need to consume `POST /chat/stream` and map `tool_call` events to Telegram messages.

### Markdown formatting

Responses are sent as plain text. Telegram's `MarkdownV2` requires aggressive escaping. A future improvement could convert Jarvis's standard Markdown to Telegram-safe formatting.
