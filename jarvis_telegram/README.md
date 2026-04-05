# Jarvis Telegram Bot

Telegram bot that connects to the Jarvis API server over UDS, letting you chat with Jarvis from your phone.

## Prerequisites

1. A running `jarvis-server` (the FastAPI server that wraps JarvisAgent).
2. A Telegram bot token from [@BotFather](https://t.me/BotFather).
3. Your Telegram user ID (send `/start` to [@userinfobot](https://t.me/userinfobot) to find it).
4. You must open the bot in Telegram and send `/start` before it can message you (Telegram requires the user to initiate the chat).

## Configuration

Set these environment variables (or export them in your shell):

| Variable | Required | Default | Description |
|---|---|---|---|
| `JARVIS_TELEGRAM_BOT_TOKEN` | Yes | — | Bot token from BotFather |
| `JARVIS_TELEGRAM_ALLOWED_USER_ID` | Yes | — | Your Telegram numeric user ID |
| `JARVIS_TELEGRAM_JARVIS_SOCKET_PATH` | No | `/tmp/jarvis.sock` | UDS path to Jarvis server |
| `JARVIS_TELEGRAM_MAX_RESPONSE_CHARS` | No | `16384` | Max chars before truncation |

## Running

```bash
# Start the Jarvis API server first
jarvis-server

# In another terminal, start the Telegram bot
jarvis-telegram
```

The bot validates the Telegram token, waits for the Jarvis server to become healthy, connects to the `/events` WebSocket, and then starts long-polling for Telegram updates.

### Startup log

```
Starting Jarvis Telegram bot
Connected to Telegram bot: @YourBotName (id=123456789)
Waiting for Jarvis server to be ready…
Jarvis server is ready
Connected to /events WebSocket
Bot is live — polling for updates
```

### Stopping

Press **Ctrl+C once** and wait for shutdown to complete:

```
Shutting down…
Event listener stopped
Jarvis client closed
Telegram bot shut down
```

Avoid pressing Ctrl+C twice — the second interrupt may skip cleanup.

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message (required on first interaction) |
| `/status` | Show Jarvis server state (model, tokens, busy) |
| `/help` | List available commands |

Any non-command text is sent to Jarvis as a chat message.

## How messages appear in Telegram

### Chat (you send text)

1. "Jarvis is typing..." appears in the chat header.
2. A **Thinking...** placeholder message appears.
3. The placeholder is **edited** with Jarvis's actual response.

### Long responses

Telegram limits messages to 4096 characters. If a response exceeds that:

- The first 4096 chars replace the **Thinking...** placeholder.
- Additional chunks arrive as new messages prefixed with **(continued...)**.

If the total response exceeds `max_response_chars` (default 16K), it is truncated with a **... (truncated)** suffix.

### Proactive alerts (heartbeat)

Heartbeat alerts from Jarvis arrive as separate messages prefixed with **[Alert]** so they are visually distinct from conversational replies.

### Errors

| Situation | What you see |
|---|---|
| Jarvis is busy (another client) | "Jarvis is busy talking to {client}. Try again shortly." |
| Jarvis timed out | "Jarvis timed out. Try again." |
| Server error | "Something went wrong. Check logs." |

## Security

Only the configured user ID can interact with the bot. All other users are silently ignored (with a warning in the log). The bot token should be stored securely (e.g. in your credential vault or a `.env` file outside version control).

## Logs

- **stderr** — INFO-level messages (what you see in the terminal).
- **`~/.jarvis/logs/telegram.log`** — DEBUG-level, rotated at 10 MB, 7-day retention.

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full system diagram, message lifecycle, and design decisions.

## Related files

- `jarvis_pa/jarvis/server/` — the Jarvis API server this bot connects to
- `jarvis_pa/jarvis/server/README.md` — server endpoint reference
- `jarvis_pa/jarvis/gated_jarvis.md` — concurrency gate design
