"""Jarvis proxy routes — /jarvis/*

Proxies to jarvis.sock. Includes:
- POST /jarvis/chat          (standard HTTP)
- POST /jarvis/chat/stream   (SSE streaming)
- GET  /jarvis/status        (standard HTTP)
- GET  /jarvis/session       (standard HTTP)
- GET  /jarvis/health        (standard HTTP)
- WS   /jarvis/events        (WebSocket proxy)
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

from fastapi import APIRouter, Request, WebSocket

from intentframe_proxy.proxy import proxy_websocket

router = APIRouter(prefix="/jarvis", tags=["jarvis"])

_BACKEND = "jarvis"


def _proxy(request: Request):
    return request.app.state.proxies[_BACKEND]


def _socket_path(conn: HTTPConnection) -> str:
    config = conn.app.state.config
    return str(config.socket_path("jarvis.sock"))


@router.get("/health")
async def jarvis_health(request: Request):
    return await _proxy(request).forward(request, "/health")


@router.get("/status")
async def jarvis_status(request: Request):
    return await _proxy(request).forward(request, "/status")


@router.get("/session")
async def jarvis_session(request: Request):
    return await _proxy(request).forward(request, "/session")


@router.post("/chat")
async def jarvis_chat(request: Request):
    return await _proxy(request).forward(request, "/chat")


@router.post("/chat/stream")
async def jarvis_chat_stream(request: Request):
    return await _proxy(request).forward_stream(request, "/chat/stream")


@router.websocket("/events")
async def jarvis_events(websocket: WebSocket):
    socket_path = _socket_path(websocket)
    await proxy_websocket(websocket, socket_path, "/events")
