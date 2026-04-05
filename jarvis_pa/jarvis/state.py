"""Concurrency gate wrapping JarvisAgent for single-client access.

GatedJarvis is a thin facade around JarvisAgent that enforces at most
one active chat/stream at a time.  If a second caller tries while the
agent is busy, ``JarvisBusy`` is raised with the identity of the
current client — the server layer converts this to a 429.

Both ``chat()`` and ``chat_stream()`` are fully managed: acquire,
delegate, release-in-finally.  No gate logic leaks to the caller.

``chat_stream()`` is a *regular function* (not an async generator)
that calls ``_acquire()`` eagerly and returns an inner async generator
whose ``finally`` calls ``_release()``.  This avoids the lazy-generator
problem: Python async generators defer body execution until first
iteration, so putting ``_acquire()`` inside the generator would fire
too late for the caller to catch ``JarvisBusy`` synchronously.

A configurable timeout (``chat_timeout_seconds``, default 600s) ensures
that a hung LLM call cannot lock the gate forever.  On timeout the gate
releases and ``GateTimeout`` is raised.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger

from jarvis.agent import JarvisAgent
from jarvis.config import JarvisConfig


class JarvisBusy(Exception):
    """Raised when a caller tries to use Jarvis while it's already busy."""

    def __init__(self, current_client: str | None) -> None:
        self.current_client = current_client
        super().__init__(
            f"Jarvis is busy talking to {current_client}. Try again shortly."
        )


class GateTimeout(Exception):
    """Raised when a chat/stream exceeds the configured timeout."""


class GatedJarvis:
    """Single-client concurrency gate around :class:`JarvisAgent`.

    Public API:
      - ``chat(message, client)`` — fully managed acquire/release.
      - ``chat_stream(message, client)`` — fully managed acquire/release.
      - ``agent`` — read-only access to the underlying JarvisAgent.
      - ``busy`` / ``current_client`` — gate state for status queries.
    """

    def __init__(self, jarvis: JarvisAgent, config: JarvisConfig) -> None:
        self._jarvis = jarvis
        self._config = config
        self._busy = False
        self._current_client: str | None = None

    # -- read-only access ----------------------------------------------------

    @property
    def agent(self) -> JarvisAgent:
        return self._jarvis

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def current_client(self) -> str | None:
        return self._current_client

    # -- gate internals ------------------------------------------------------

    def _acquire(self, client: str) -> None:
        if self._busy:
            raise JarvisBusy(self._current_client)
        self._busy = True
        self._current_client = client

    def _release(self) -> None:
        self._busy = False
        self._current_client = None

    # -- fully managed methods -----------------------------------------------

    async def chat(self, message: str, client: str) -> str:
        """Acquire, run ``agent.chat()``, release.  Fully managed."""
        self._acquire(client)
        try:
            return await asyncio.wait_for(
                self._jarvis.chat(message),
                timeout=self._config.chat_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(f"Chat timed out after {self._config.chat_timeout_seconds}s for client {client!r}")
            raise GateTimeout(f"Chat timed out after {self._config.chat_timeout_seconds}s")
        finally:
            self._release()

    def chat_stream(
        self, message: str, client: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Acquire eagerly, return an async generator that releases on close.

        This is a regular function — ``_acquire()`` runs immediately when
        called, not lazily on first iteration.  The returned generator's
        ``finally`` block calls ``_release()`` when the stream ends, errors,
        or the consumer disconnects.
        """
        self._acquire(client)
        timeout = self._config.chat_timeout_seconds

        async def _stream() -> AsyncGenerator[dict[str, Any], None]:
            try:
                deadline = asyncio.get_event_loop().time() + timeout
                async for event in self._jarvis.chat_stream(message):
                    if asyncio.get_event_loop().time() > deadline:
                        logger.error(f"Stream timed out after {timeout}s for client {client!r}")
                        yield {"type": "error", "error": f"Stream timed out after {timeout}s"}
                        return
                    yield event
            finally:
                self._release()

        return _stream()
