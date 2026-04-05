"""Integration tests for Jarvis API server concurrency gate.

Verifies that GatedJarvis correctly enforces single-client access:
  - Only one chat/stream runs at a time
  - Concurrent requests get 429 with the current client's identity
  - Read-only endpoints respond even while busy
  - The gate releases after chat, stream completion, and client disconnect
  - Cross-type rejection (chat blocks stream and vice versa)

Requirements:
    - Jarvis server must be running.

Run (UDS — default):
    python jarvis_pa/test_server_gate.py

Run (TCP):
    python jarvis_pa/test_server_gate.py --tcp

Flags:
    --tcp       Connect to 127.0.0.1:8100 instead of UDS
    --socket    UDS path (default: /tmp/jarvis.sock)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

CLIENT_A = "test-client-A"
CLIENT_B = "test-client-B"

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0
_errors: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  pass  {name}")
    else:
        _failed += 1
        msg = f"  FAIL  {name}{f': {detail}' if detail else ''}"
        _errors.append(msg)
        print(msg)


def _build_client(*, tcp: bool, socket: str) -> httpx.AsyncClient:
    """Return an httpx async client for UDS or TCP."""
    if tcp:
        return httpx.AsyncClient(base_url="http://127.0.0.1:8100")

    transport = httpx.AsyncHTTPTransport(uds=socket)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://jarvis-local",
    )


# ---------------------------------------------------------------------------
# Read-only endpoint tests
# ---------------------------------------------------------------------------

async def test_health(c: httpx.AsyncClient) -> None:
    r = await c.get("/health")
    _check("health returns 200", r.status_code == 200, f"got {r.status_code}")
    _check("health body ok", r.json().get("status") == "ok", f"got {r.json()}")


async def test_status_idle(c: httpx.AsyncClient) -> None:
    r = await c.get("/status")
    _check("status returns 200", r.status_code == 200, f"got {r.status_code}")
    data = r.json()
    _check("status.busy is False when idle", data.get("busy") is False, f"got {data}")
    _check(
        "status.current_client is null when idle",
        data.get("current_client") is None,
        f"got {data}",
    )


async def test_session(c: httpx.AsyncClient) -> None:
    r = await c.get("/session")
    _check("session returns 200", r.status_code == 200, f"got {r.status_code}")
    data = r.json()
    _check("session has messages key", "messages" in data, f"keys: {list(data)}")
    _check("session has tokens key", "tokens" in data, f"keys: {list(data)}")


# ---------------------------------------------------------------------------
# Chat tests
# ---------------------------------------------------------------------------

async def test_chat_basic(c: httpx.AsyncClient) -> None:
    """Happy-path: single /chat returns a response and releases the gate."""
    r = await c.post(
        "/chat",
        json={"message": "Say hello in exactly 3 words.", "client": CLIENT_A},
        timeout=120.0,
    )
    _check("chat returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        data = r.json()
        _check("chat has response", bool(data.get("response")), f"got {data}")
        _check("chat has tokens", "tokens" in data, f"keys: {list(data)}")

    r = await c.get("/status")
    _check("gate idle after chat", r.json().get("busy") is False, f"got {r.json()}")


async def test_concurrent_chat_rejection(c: httpx.AsyncClient) -> None:
    """Second /chat gets 429 while first is processing."""

    async def slow_chat() -> httpx.Response:
        return await c.post(
            "/chat",
            json={
                "message": "Write a limerick about the sea. Be creative.",
                "client": CLIENT_A,
            },
            timeout=120.0,
        )

    task = asyncio.create_task(slow_chat())
    await asyncio.sleep(1.0)

    r2 = await c.post(
        "/chat",
        json={"message": "hi", "client": CLIENT_B},
        timeout=10.0,
    )
    _check("concurrent chat → 429", r2.status_code == 429, f"got {r2.status_code}: {r2.text[:200]}")

    if r2.status_code == 429:
        detail = r2.json().get("detail", {})
        _check("429 has error=busy", detail.get("error") == "busy", f"got {detail}")
        _check(
            "429 reports current_client=A",
            detail.get("current_client") == CLIENT_A,
            f"got {detail}",
        )

    r1 = await task
    _check("first chat completed 200", r1.status_code == 200, f"got {r1.status_code}")

    r = await c.get("/status")
    _check("gate idle after concurrent test", r.json().get("busy") is False, f"got {r.json()}")


# ---------------------------------------------------------------------------
# Read-only while busy
# ---------------------------------------------------------------------------

async def test_read_only_during_busy(c: httpx.AsyncClient) -> None:
    """Health, status, session respond while a chat is running."""

    async def slow_chat() -> httpx.Response:
        return await c.post(
            "/chat",
            json={"message": "Write a haiku about mountains.", "client": CLIENT_A},
            timeout=120.0,
        )

    task = asyncio.create_task(slow_chat())
    await asyncio.sleep(1.0)

    r = await c.get("/health")
    _check("health works while busy", r.status_code == 200, f"got {r.status_code}")

    r = await c.get("/status")
    _check("status works while busy", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        _check("status.busy=True during chat", data.get("busy") is True, f"got {data}")
        _check(
            "status.current_client=A during chat",
            data.get("current_client") == CLIENT_A,
            f"got {data}",
        )

    r = await c.get("/session")
    _check("session works while busy", r.status_code == 200, f"got {r.status_code}")

    await task


# ---------------------------------------------------------------------------
# Stream tests
# ---------------------------------------------------------------------------

async def test_stream_basic(c: httpx.AsyncClient) -> None:
    """Happy-path: /chat/stream returns SSE events ending with 'done'."""
    events: list[dict] = []

    async with c.stream(
        "POST",
        "/chat/stream",
        json={"message": "Say hi in 3 words.", "client": CLIENT_A},
        timeout=120.0,
    ) as resp:
        _check("stream returns 200", resp.status_code == 200, f"got {resp.status_code}")
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass

    types = [e.get("type") for e in events]
    _check("stream has text_delta events", "text_delta" in types, f"types: {types}")
    _check("stream has done event", "done" in types, f"types: {types}")

    done = [e for e in events if e.get("type") == "done"]
    if done:
        _check("done event has response", bool(done[0].get("response")), f"got {done[0]}")

    r = await c.get("/status")
    _check("gate idle after stream", r.json().get("busy") is False, f"got {r.json()}")


async def test_concurrent_stream_rejection(c: httpx.AsyncClient) -> None:
    """While streaming, a second /chat and /chat/stream both get 429."""

    long_prompt = (
        "Write a detailed, multi-paragraph essay about the history of "
        "artificial intelligence from the 1950s to today. Cover Turing, "
        "the Dartmouth conference, expert systems, the AI winters, deep "
        "learning, transformers, and large language models. Use at least "
        "500 words."
    )

    async with c.stream(
        "POST",
        "/chat/stream",
        json={"message": long_prompt, "client": CLIENT_A},
        timeout=180.0,
    ) as resp:
        _check("stream started 200", resp.status_code == 200, f"got {resp.status_code}")

        async def fire_concurrent_checks():
            """Send rejection requests while the stream is still active."""
            r2 = await c.post(
                "/chat",
                json={"message": "hi", "client": CLIENT_B},
                timeout=10.0,
            )
            _check("chat during stream → 429", r2.status_code == 429, f"got {r2.status_code}")

            if r2.status_code == 429:
                detail = r2.json().get("detail", {})
                _check(
                    "429 reports current_client during stream",
                    detail.get("current_client") == CLIENT_A,
                    f"got {detail}",
                )

            r3 = await c.post(
                "/chat/stream",
                json={"message": "hi", "client": CLIENT_B},
                timeout=10.0,
            )
            _check("stream-on-stream → 429", r3.status_code == 429, f"got {r3.status_code}")

        checks_task = asyncio.create_task(fire_concurrent_checks())

        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("type") == "done":
                    break

        await checks_task

    await asyncio.sleep(0.5)
    r = await c.get("/status")
    _check("gate idle after stream rejection test", r.json().get("busy") is False, f"got {r.json()}")


# ---------------------------------------------------------------------------
# Cross-type rejection: chat blocks stream
# ---------------------------------------------------------------------------

async def test_chat_blocks_stream(c: httpx.AsyncClient) -> None:
    """A running /chat rejects a concurrent /chat/stream."""

    async def slow_chat() -> httpx.Response:
        return await c.post(
            "/chat",
            json={"message": "Write a limerick about cats.", "client": CLIENT_A},
            timeout=120.0,
        )

    task = asyncio.create_task(slow_chat())
    await asyncio.sleep(1.0)

    r = await c.post(
        "/chat/stream",
        json={"message": "hi", "client": CLIENT_B},
        timeout=10.0,
    )
    _check("stream rejected while chat running → 429", r.status_code == 429, f"got {r.status_code}")

    await task

    r = await c.get("/status")
    _check("gate idle after cross-type test", r.json().get("busy") is False, f"got {r.json()}")


# ---------------------------------------------------------------------------
# Stream disconnect releases gate
# ---------------------------------------------------------------------------

async def test_stream_disconnect_releases_gate(c: httpx.AsyncClient) -> None:
    """Disconnecting mid-stream releases the gate for the next caller."""

    async with c.stream(
        "POST",
        "/chat/stream",
        json={
            "message": "Write a very long essay about the history of computing.",
            "client": "disconnect-test",
        },
        timeout=120.0,
    ) as resp:
        _check("disconnect: stream started 200", resp.status_code == 200, f"got {resp.status_code}")
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                break

    await asyncio.sleep(1.5)

    r = await c.get("/status")
    data = r.json()
    _check("gate idle after disconnect", data.get("busy") is False, f"got {data}")

    r = await c.post(
        "/chat",
        json={"message": "Say ok.", "client": "post-disconnect"},
        timeout=120.0,
    )
    _check("chat works after disconnect", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")


# ---------------------------------------------------------------------------
# 429 body shape
# ---------------------------------------------------------------------------

async def test_429_body_shape(c: httpx.AsyncClient) -> None:
    """Verify the 429 JSON body has the expected schema."""

    async def slow_chat() -> httpx.Response:
        return await c.post(
            "/chat",
            json={"message": "Write a short poem.", "client": CLIENT_A},
            timeout=120.0,
        )

    task = asyncio.create_task(slow_chat())
    await asyncio.sleep(1.0)

    r = await c.post(
        "/chat",
        json={"message": "hi", "client": CLIENT_B},
        timeout=10.0,
    )

    if r.status_code == 429:
        body = r.json()
        detail = body.get("detail", {})
        _check("429 detail has 'error' key", "error" in detail, f"got {detail}")
        _check("429 detail has 'message' key", "message" in detail, f"got {detail}")
        _check("429 detail has 'current_client' key", "current_client" in detail, f"got {detail}")
        _check(
            "429 message mentions current client",
            CLIENT_A in detail.get("message", ""),
            f"got message: {detail.get('message')}",
        )
    else:
        _check("429 body shape (skipped — not 429)", False, f"got {r.status_code}")

    await task


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis server gate integration tests")
    parser.add_argument("--tcp", action="store_true", help="Connect via TCP 127.0.0.1:8100")
    parser.add_argument("--socket", default="/tmp/jarvis.sock", help="UDS path (default: /tmp/jarvis.sock)")
    args = parser.parse_args()

    transport = "TCP 127.0.0.1:8100" if args.tcp else f"UDS {args.socket}"
    print("Jarvis Server Gate Tests")
    print(f"Transport: {transport}")
    print("=" * 60)

    if not args.tcp:
        sock = Path(args.socket)
        if not sock.exists():
            print(f"Socket not found: {sock}")
            print("Start the server: jarvis-server")
            sys.exit(1)

    async with _build_client(tcp=args.tcp, socket=args.socket) as c:
        try:
            r = await c.get("/health", timeout=5.0)
            if r.status_code != 200:
                flag = "--tcp" if args.tcp else ""
                print(f"Server returned {r.status_code} — is jarvis-server {flag} running?")
                sys.exit(1)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            print(f"Cannot connect via {transport}")
            print("Start the server: jarvis-server" + (" --tcp" if args.tcp else ""))
            sys.exit(1)

        r = await c.get("/status")
        if r.json().get("busy"):
            print("Server is currently busy — wait for it to become idle.")
            sys.exit(1)

        print("Server reachable and idle. Running tests…\n")

        print("=== READ-ONLY ENDPOINTS ===")
        await test_health(c)
        await test_status_idle(c)
        await test_session(c)

        print("\n=== BASIC CHAT ===")
        await test_chat_basic(c)

        print("\n=== BASIC STREAM ===")
        await test_stream_basic(c)

        print("\n=== CONCURRENT CHAT REJECTION ===")
        await test_concurrent_chat_rejection(c)

        print("\n=== READ-ONLY WHILE BUSY ===")
        await test_read_only_during_busy(c)

        print("\n=== 429 BODY SHAPE ===")
        await test_429_body_shape(c)

        print("\n=== STREAM CONCURRENCY ===")
        await test_concurrent_stream_rejection(c)

        print("\n=== CHAT BLOCKS STREAM ===")
        await test_chat_blocks_stream(c)

        print("\n=== STREAM DISCONNECT ===")
        await test_stream_disconnect_releases_gate(c)

    total = _passed + _failed
    print(f"\n{'=' * 60}")
    print(f"Results: {_passed}/{total} passed, {_failed} failed")
    if _errors:
        print("\nFailures:")
        for e in _errors:
            print(e)
    print("=" * 60)
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
