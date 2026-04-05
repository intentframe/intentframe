# Jarvis API Server

FastAPI server that wraps `JarvisAgent` and exposes it over HTTP (UDS or TCP) so any local client — Telegram bot, dashboard, CLI — can talk to Jarvis.

## The problem

Jarvis is a stateful, single-agent system. It has one session, one memory, one LLM context. If two clients send messages simultaneously, the shared state corrupts: interleaved responses, mangled session history, crashes.

The requirement: **one active chat at a time**. If a second client tries while Jarvis is busy, reject immediately with a 429 and tell them who is currently talking.

## Why the obvious approaches fail

### FastAPI `Depends()` with a generator dependency

The first attempt used a FastAPI async generator dependency (`acquire_jarvis`) to set a `busy` flag and clear it in `finally`:

```python
async def acquire_jarvis(request):
    state.busy = True
    try:
        yield state
    finally:
        state.busy = False      # <-- runs when the route handler returns
```

This works for `/chat` (the handler awaits the LLM call, then returns). It **breaks for `/chat/stream`**: the handler returns an `EventSourceResponse` object immediately, and FastAPI's dependency cleanup fires before the SSE stream even starts. The gate releases while the LLM is still running.

### Putting `_acquire()` inside an async generator wrapper

The next attempt wrapped `chat_stream` as an async generator on `GatedJarvis`:

```python
async def chat_stream(self, message, client):
    self._acquire(client)   # inside the generator body
    try:
        async for event in self._jarvis.chat_stream(message):
            yield event
    finally:
        self._release()
```

Python async generators are **lazy** — the body doesn't execute until first iteration. So `gated.chat_stream(msg, client)` returns a generator object without running `_acquire()`. The route's `try/except JarvisBusy` is dead code — it can never fire. A busy agent gets a 200 + SSE headers, then an error event deep in the stream, instead of a clean 429.

### ASGI middleware

Wrapping the full request lifecycle at the ASGI level works correctly for both streaming and non-streaming. But it's HTTP-specific, requires manual 429 response construction at the raw ASGI level, and introduces a `current_client` race (the middleware sets `busy=True` before the body is parsed, so the 429 reports `current_client=None` briefly).

## The solution: `GatedJarvis` wrapper

A thin facade around `JarvisAgent` that lives at `jarvis/state.py`, independent of the server layer.

### `chat()` — fully managed with timeout

```python
async def chat(self, message, client):
    self._acquire(client)       # raises JarvisBusy if busy
    try:
        return await asyncio.wait_for(
            self._jarvis.chat(message),
            timeout=self._config.chat_timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise GateTimeout(...)
    finally:
        self._release()
```

Acquire, await the full LLM call with a configurable timeout (default 600s / 10 minutes), release in `finally`. If the LLM hangs (network partition, provider outage), the gate auto-releases after the timeout instead of locking forever. `GateTimeout` is translated to HTTP 504 by the route layer.

### `chat_stream()` — regular function returning an async generator

```python
def chat_stream(self, message, client):
    self._acquire(client)       # eager — runs immediately, not lazily

    async def _stream():
        try:
            async for event in self._jarvis.chat_stream(message):
                yield event
        finally:
            self._release()     # runs when stream ends, errors, or disconnects

    return _stream()
```

`chat_stream` is a **regular function**, not an async generator. `_acquire()` runs immediately when called — not deferred until first iteration. If busy, `JarvisBusy` is raised synchronously and the caller catches it cleanly.

The returned `_stream()` generator holds the gate for the entire streaming duration. Its `finally` fires in all cases:
- Stream completes normally
- Exception during streaming
- Client disconnects (sse-starlette closes the generator)
- `GeneratorExit` from GC

### Routes are just translators

The server routes contain zero gate logic. They call `GatedJarvis` methods and translate exceptions to HTTP status codes:

- `JarvisBusy` → 429 (busy, try again)
- `GateTimeout` → 504 (timed out)
- Any other exception → 500 (structured error body with type + message)

For streaming, the `event_generator` wrapper catches mid-flight exceptions and emits a final SSE error event so the client gets a clean signal instead of a broken connection.

### Why it's race-free

`_acquire()` checks `self._busy` and sets it to `True` with no `await` in between. In asyncio's cooperative model, this is atomic — another coroutine cannot be scheduled between the check and the set.

## Endpoints

| Method | Path | Gated | Description |
|--------|------|-------|-------------|
| GET | `/health` | No | Always returns `{"status": "ok"}` |
| GET | `/status` | No | Agent readiness, model, tokens, busy state |
| GET | `/session` | No | Current session messages and token count |
| POST | `/chat` | Yes | Synchronous chat, returns full response |
| POST | `/chat/stream` | Yes | SSE streaming chat |
| WS | `/events` | No | Proactive push (heartbeat alerts) |

## Running

```bash
# UDS (default — what the supervisor and local clients use)
jarvis-server

# TCP (for development/testing)
jarvis-server --tcp
```

## Testing

```bash
# Against UDS (default)
python jarvis_pa/test_server_gate.py

# Against TCP
python jarvis_pa/test_server_gate.py --tcp
```

Tests verify: basic chat/stream, concurrent rejection with client identity, read-only endpoints during busy state, cross-type rejection (chat blocks stream and vice versa), stream disconnect releases gate, and 429 response shape.
