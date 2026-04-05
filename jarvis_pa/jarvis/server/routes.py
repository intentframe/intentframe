"""Jarvis API route handlers.

Read-only endpoints (health, status, session) always respond.
Chat-mutating endpoints go through GatedJarvis, which fully manages
concurrency — the route layer only translates JarvisBusy to HTTP 429
and GateTimeout to HTTP 504.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from jarvis.state import GateTimeout, JarvisBusy
from jarvis.server.schemas import (
    ChatRequest,
    ChatResponse,
    SessionResponse,
    StatusResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Read-only endpoints — always respond, even when Jarvis is busy
# ---------------------------------------------------------------------------

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "jarvis"}


@router.get("/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    gated = request.app.state.gated_jarvis
    jarvis = gated.agent
    return StatusResponse(
        ready=jarvis.agent is not None,
        model=jarvis.config.model,
        session_tokens=jarvis.session.estimate_tokens(),
        heartbeat_enabled=jarvis.config.heartbeat_enabled,
        busy=gated.busy,
        current_client=gated.current_client,
    )


@router.get("/session", response_model=SessionResponse)
async def get_session(request: Request) -> SessionResponse:
    jarvis = request.app.state.gated_jarvis.agent
    return SessionResponse(
        messages=jarvis.session.to_openai_messages(),
        tokens=jarvis.session.estimate_tokens(),
    )


# ---------------------------------------------------------------------------
# Chat-mutating endpoints — guarded by GatedJarvis
# ---------------------------------------------------------------------------

def _busy_response(exc: JarvisBusy) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "error": "busy",
            "message": str(exc),
            "current_client": exc.current_client,
        },
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    gated = request.app.state.gated_jarvis
    logger.info(f"[{body.client}] chat: {body.message[:80]!r}")

    try:
        response = await gated.chat(body.message, body.client)
    except JarvisBusy as exc:
        raise _busy_response(exc) from exc
    except GateTimeout as exc:
        raise HTTPException(status_code=504, detail={"error": "timeout", "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception(f"[{body.client}] chat failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "internal", "message": f"Chat failed: {type(exc).__name__}: {exc}"},
        ) from exc

    return ChatResponse(
        response=response,
        tokens=gated.agent.session.estimate_tokens(),
    )


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> EventSourceResponse:
    gated = request.app.state.gated_jarvis
    logger.info(f"[{body.client}] chat/stream: {body.message[:80]!r}")

    try:
        stream = gated.chat_stream(body.message, body.client)
    except JarvisBusy as exc:
        raise _busy_response(exc) from exc

    async def event_generator():
        try:
            async for event in stream:
                yield {
                    "event": event["type"],
                    "data": json.dumps(event, default=str),
                }
        except Exception as exc:
            logger.exception(f"[{body.client}] stream failed mid-flight")
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "error": f"{type(exc).__name__}: {exc}"}, default=str),
            }

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Event subscription — proactive push (heartbeat alerts, notifications)
# ---------------------------------------------------------------------------

@router.websocket("/events")
async def events(websocket: WebSocket):
    await websocket.accept()
    event_bus = websocket.app.state.event_bus
    queue = event_bus.subscribe()

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning(f"WebSocket /events error: {exc}")
    finally:
        event_bus.unsubscribe(queue)
