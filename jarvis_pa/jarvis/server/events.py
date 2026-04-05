"""Async event bus for proactive messages (heartbeat alerts, notifications).

Subscribers get their own asyncio.Queue. The bus fans out every published
event to all connected subscribers.
"""

from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    """Lightweight pub/sub for pushing events to connected clients."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    _MAX_QUEUE_SIZE = 128

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._MAX_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: dict[str, Any]) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if a subscriber is not draining fast enough.

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
