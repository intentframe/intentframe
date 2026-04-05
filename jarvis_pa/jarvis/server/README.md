# Jarvis API Server

FastAPI server that wraps `JarvisAgent` and exposes it over HTTP (UDS or TCP) so any local client — Telegram bot, dashboard, CLI — can talk to Jarvis.

## Quick start

```bash
# UDS (default — what the supervisor and local clients use)
jarvis-server

# TCP (for development/testing)
jarvis-server --tcp

# Custom socket path
jarvis-server --socket /var/run/jarvis.sock
```

The server runs Jarvis setup on startup (handshake, workspace bootstrap, memory indexing, skill discovery, prompt building, heartbeat start) and shuts down gracefully on SIGTERM.

Stale UDS socket files from a previous crash are automatically cleaned up before binding.

## Endpoints

| Method | Path | Gated | Description |
|--------|------|-------|-------------|
| GET | `/health` | No | Always returns `{"status": "ok"}` |
| GET | `/status` | No | Agent readiness, model, tokens, busy state |
| GET | `/session` | No | Current session messages and token count |
| POST | `/chat` | Yes | Synchronous chat, returns full response |
| POST | `/chat/stream` | Yes | SSE streaming chat |
| WS | `/events` | No | Proactive push (heartbeat alerts, notifications) |

## Request / response schemas

### `POST /chat`

Request:

```json
{
  "message": "What's on my calendar today?",
  "client": "telegram"
}
```

`client` is optional (defaults to `"unknown"`). It identifies the caller in busy-rejection messages and the `/status` endpoint.

Response (200):

```json
{
  "response": "You have 3 meetings today...",
  "tokens": 2847
}
```

### `POST /chat/stream`

Same request body as `/chat`. Returns an SSE stream with these event types:

```
event: text_delta
data: {"type": "text_delta", "delta": "You have "}

event: text_delta
data: {"type": "text_delta", "delta": "3 meetings"}

event: tool_call
data: {"type": "tool_call", "name": "list_events", "arguments": "..."}

event: done
data: {"type": "done", "response": "You have 3 meetings today...", "tokens": 2847}
```

On error mid-stream:

```
event: error
data: {"type": "error", "error": "TimeoutError: Stream timed out after 600s"}
```

### `GET /status`

```json
{
  "ready": true,
  "model": "gpt-5-mini-2025-08-07",
  "session_tokens": 2847,
  "heartbeat_enabled": true,
  "busy": false,
  "current_client": null
}
```

### `GET /session`

```json
{
  "messages": [
    {"role": "user", "content": "What's on my calendar?"},
    {"role": "assistant", "content": "You have 3 meetings..."}
  ],
  "tokens": 2847
}
```

### `WS /events`

WebSocket endpoint for proactive push events. Connect and receive JSON messages:

```json
{"type": "heartbeat_alert", "message": "You have an unread email from..."}
```

## Concurrency gate

Jarvis is a stateful, single-agent system. If two clients send messages simultaneously, shared state corrupts. The server enforces **one active chat at a time** via `GatedJarvis` (`jarvis/state.py`).

- Second client gets an immediate **429** with the identity of the current client.
- Read-only endpoints (`/health`, `/status`, `/session`) always respond, even while busy.
- A configurable **timeout** (default 600s / 10 minutes) auto-releases the gate if the LLM hangs.

### Error responses

| Status | Error | When |
|--------|-------|------|
| 429 | `busy` | Another client is using Jarvis |
| 504 | `timeout` | Chat exceeded `chat_timeout_seconds` |
| 500 | `internal` | LLM error, runtime error, etc. |

429 body:

```json
{
  "detail": {
    "error": "busy",
    "message": "Jarvis is busy talking to telegram. Try again shortly.",
    "current_client": "telegram"
  }
}
```

504 body:

```json
{
  "detail": {
    "error": "timeout",
    "message": "Chat timed out after 600s"
  }
}
```

500 body:

```json
{
  "detail": {
    "error": "internal",
    "message": "Chat failed: RuntimeError: call setup() before chat()"
  }
}
```

### How the gate works

See [`gated_jarvis.md`](../gated_jarvis.md) for the full design rationale, including why `Depends()`, lazy async generators, and ASGI middleware all fail for streaming, and how `GatedJarvis` solves it.

Short version:

- `chat()` uses `asyncio.wait_for()` with the configured timeout. `JarvisBusy` on contention, `GateTimeout` on timeout, release in `finally`.
- `chat_stream()` is a regular function (not async generator) that calls `_acquire()` eagerly. Returns an inner async generator whose `finally` calls `_release()`. The deadline is checked on every yielded event.
- Routes are pure translators — zero gate logic, just exception-to-HTTP-status mapping.

## Configuration

Server-relevant settings in `config.yaml` or `JARVIS_*` env vars:

| Setting | Default | Description |
|---------|---------|-------------|
| `chat_timeout_seconds` | `600` | Max seconds before gate auto-releases a hung chat |

## Known clients

| Client | Transport | Endpoints used | Source |
|--------|-----------|----------------|--------|
| `jarvis-cli-client` | UDS (httpx sync) | `/chat/stream`, `/health` | `jarvis_pa/jarvis/server_cli.py` |
| `jarvis-telegram` | UDS (httpx async) | `/chat`, `/health`, `/status`, `/events` | `jarvis_telegram/` |

## Client examples

### Python (httpx, UDS)

```python
import httpx

transport = httpx.HTTPTransport(uds="/tmp/jarvis.sock")
client = httpx.Client(transport=transport, base_url="http://jarvis-local")

# Synchronous chat
r = client.post("/chat", json={"message": "Hello", "client": "my-app"})
print(r.json()["response"])

# Check status
print(client.get("/status").json())
```

### Python (httpx, TCP)

```python
import httpx

client = httpx.Client(base_url="http://127.0.0.1:8100")
r = client.post("/chat", json={"message": "Hello", "client": "my-app"})
print(r.json()["response"])
```

### Python (SSE streaming)

```python
import httpx, json

transport = httpx.HTTPTransport(uds="/tmp/jarvis.sock")
with httpx.Client(transport=transport, base_url="http://jarvis-local") as client:
    with client.stream("POST", "/chat/stream", json={"message": "Hello", "client": "my-app"}) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:])
                if event["type"] == "text_delta":
                    print(event["delta"], end="", flush=True)
                elif event["type"] == "done":
                    print()
```

### curl (TCP)

```bash
# Chat
curl -X POST http://127.0.0.1:8100/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "client": "curl"}'

# Stream
curl -N -X POST http://127.0.0.1:8100/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "client": "curl"}'

# Status
curl http://127.0.0.1:8100/status
```

## Testing

Gate integration tests verify single-client concurrency enforcement against a live server.

```bash
# 1. Start the server
jarvis-server --tcp

# 2. Run tests (in another terminal)
python jarvis_pa/test_server_gate.py --tcp
```

For UDS:

```bash
jarvis-server
python jarvis_pa/test_server_gate.py
```

Flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--tcp` | off | Connect via TCP instead of UDS |
| `--socket PATH` | `/tmp/jarvis.sock` | UDS socket path |

Test coverage:

- Read-only endpoints respond correctly
- Basic `/chat` and `/chat/stream` happy paths
- Concurrent rejection (429 with correct client identity)
- Read-only endpoints still work while busy
- 429 body shape validation
- Stream concurrency (chat-during-stream, stream-on-stream)
- Cross-type rejection (chat blocks stream and vice versa)
- Stream disconnect releases gate
