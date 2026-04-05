"""Unified event stream routes — /events/*

Frontend endpoints for the merged event stream.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["events"])

logger = logging.getLogger(__name__)


@router.websocket("/events")
async def events_ws(websocket: WebSocket):
    """WebSocket endpoint for the unified event stream."""
    await websocket.accept()
    stream = websocket.app.state.event_stream
    queue = stream.subscribe()

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("Unified events WebSocket error: %s", exc)
    finally:
        stream.unsubscribe(queue)


@router.get("/events/stream")
async def events_sse(request: Request):
    """SSE endpoint for the unified event stream."""
    stream = request.app.state.event_stream
    queue = stream.subscribe()

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event),
                }
        except asyncio.CancelledError:
            pass
        finally:
            stream.unsubscribe(queue)

    return EventSourceResponse(event_generator())
