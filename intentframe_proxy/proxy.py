"""Generic UDS proxy helper.

Forwards HTTP requests to a backend service over a Unix Domain Socket.
Shared by ``intentframe_gateway`` (consumer product API) and
``intentframe_edge`` (B2B network ingress). Uses the same httpx UDS
transport pattern as intentframe_server/client.py and the registry clients.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import Request, Response, WebSocket, WebSocketDisconnect
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


class UDSProxy:
    """Forward HTTP requests to a backend service over UDS.

    One instance per backend service. Holds a persistent httpx.AsyncClient
    that is created lazily and reused across requests.
    """

    def __init__(
        self,
        socket_path: str | Path,
        base_url: str,
        timeout: float = 30.0,
    ) -> None:
        self._socket_path = str(socket_path)
        self._base_url = base_url
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            transport = httpx.AsyncHTTPTransport(uds=self._socket_path)
            self._client = httpx.AsyncClient(
                transport=transport,
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health(self, health_path: str = "/health") -> bool:
        """Single health probe. Returns True if 200, False otherwise."""
        try:
            client = await self._get_client()
            resp = await client.get(health_path, timeout=5.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.ReadError, OSError) as exc:
            logger.debug(
                "Health probe failed (%s %s): %s",
                self._socket_path,
                health_path,
                exc,
            )
            return False

    async def forward(self, request: Request, backend_path: str) -> Response:
        """Forward an HTTP request and return the complete response."""
        client = await self._get_client()

        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)

        resp = await client.request(
            method=request.method,
            url=backend_path,
            content=body,
            headers=headers,
            params=dict(request.query_params),
        )

        resp_headers = dict(resp.headers)
        for h in ("content-encoding", "content-length"):
            resp_headers.pop(h, None)

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=resp.headers.get("content-type"),
        )

    async def forward_stream(
        self, request: Request, backend_path: str
    ) -> StreamingResponse:
        """Forward a request and stream the response back (SSE, chunked)."""
        client = await self._get_client()

        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)

        req = client.build_request(
            method=request.method,
            url=backend_path,
            content=body,
            headers=headers,
            params=dict(request.query_params),
        )

        backend_resp = await client.send(req, stream=True)

        async def stream_body() -> AsyncIterator[bytes]:
            try:
                async for chunk in backend_resp.aiter_bytes():
                    yield chunk
            finally:
                await backend_resp.aclose()

        resp_headers = dict(backend_resp.headers)
        for h in ("content-encoding", "content-length", "transfer-encoding"):
            resp_headers.pop(h, None)

        return StreamingResponse(
            content=stream_body(),
            status_code=backend_resp.status_code,
            headers=resp_headers,
            media_type=backend_resp.headers.get("content-type"),
        )


async def proxy_websocket(
    frontend_ws: WebSocket,
    socket_path: str | Path,
    backend_path: str = "/events",
) -> None:
    """Bidirectional WebSocket proxy over UDS.

    Uses the websockets library with unix=True, matching the pattern
    from jarvis_telegram/bot.py.
    """
    from websockets.asyncio.client import connect

    await frontend_ws.accept()
    uri = f"ws://backend{backend_path}"

    try:
        async with connect(uri, unix=True, path=str(socket_path)) as backend_ws:

            async def forward_to_client() -> None:
                async for msg in backend_ws:
                    if isinstance(msg, str):
                        await frontend_ws.send_text(msg)
                    else:
                        await frontend_ws.send_bytes(msg)

            async def forward_to_backend() -> None:
                while True:
                    msg = await frontend_ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "text" in msg:
                        await backend_ws.send(msg["text"])
                    elif "bytes" in msg and msg["bytes"]:
                        await backend_ws.send(msg["bytes"])

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(forward_to_client()),
                    asyncio.create_task(forward_to_backend()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket proxy closed: %s", exc)
        try:
            await frontend_ws.close(code=1011, reason="Backend unavailable")
        except Exception:
            pass
