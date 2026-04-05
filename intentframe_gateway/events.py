"""Unified event stream — merges multiple event sources.

Sources:
- Jarvis proactive alerts (from jarvis /events WebSocket)
- Service health changes (from periodic /health polls on all sockets)

Frontend connects to WS /events or GET /events/stream (SSE) and gets everything.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, UTC
from typing import Any

from intentframe_gateway.config import GatewayConfig
from intentframe_gateway.proxy import UDSProxy

logger = logging.getLogger(__name__)


class UnifiedEventStream:
    """Merges events from multiple sources into subscriber queues."""

    _MAX_QUEUE_SIZE = 256

    def __init__(self, config: GatewayConfig, proxies: dict[str, UDSProxy]) -> None:
        self._config = config
        self._proxies = proxies
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._tasks: list[asyncio.Task] = []
        self._last_health: dict[str, bool] = {}
        self._last_queue_full_warn = 0.0

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._health_poller()))
        self._tasks.append(asyncio.create_task(self._jarvis_listener()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._MAX_QUEUE_SIZE
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def _publish(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", datetime.now(UTC).isoformat())
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                now = time.monotonic()
                if now - self._last_queue_full_warn >= 5.0:
                    logger.warning(
                        "Unified event subscriber queue full; dropping events "
                        "(maxsize=%d)",
                        self._MAX_QUEUE_SIZE,
                    )
                    self._last_queue_full_warn = now

    # --- Health change poller ---

    async def _health_poller(self) -> None:
        """Periodically poll all backends and emit events on status changes."""
        while True:
            try:
                for backend in self._config.backends:
                    proxy = self._proxies.get(backend.name)
                    if not proxy:
                        continue

                    healthy = await proxy.health(backend.health_path)
                    prev = self._last_health.get(backend.name)

                    if prev is not None and prev != healthy:
                        await self._publish({
                            "source": "health",
                            "type": "health_changed",
                            "service": backend.name,
                            "healthy": healthy,
                            "previous": prev,
                        })

                    self._last_health[backend.name] = healthy

                await asyncio.sleep(self._config.health_poll_interval)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Health poller error: %s", exc)
                await asyncio.sleep(self._config.health_poll_interval)

    # --- Jarvis /events WebSocket listener ---

    async def _jarvis_listener(self) -> None:
        """Connect to Jarvis /events WS and republish as unified events."""
        from websockets.asyncio.client import connect

        socket_path = str(self._config.socket_path("jarvis.sock"))
        uri = "ws://jarvis-local/events"

        while True:
            try:
                async with connect(uri, unix=True, path=socket_path) as ws:
                    logger.info("Connected to Jarvis /events for unified stream")
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            text = (
                                raw.decode("utf-8", errors="replace")
                                if isinstance(raw, (bytes, bytearray))
                                else raw
                            )
                            preview = text if len(text) <= 200 else text[:200] + "..."
                            logger.debug(
                                "Invalid JSON from Jarvis /events: %r", preview
                            )
                            continue

                        await self._publish({
                            "source": "jarvis",
                            "type": event.get("type", "unknown"),
                            "data": event,
                        })
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("Jarvis event listener reconnecting: %s", exc)
                await asyncio.sleep(3.0)
