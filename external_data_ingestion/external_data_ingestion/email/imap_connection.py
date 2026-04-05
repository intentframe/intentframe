"""Centralised IMAP connection provider.

Every IMAP connection in the codebase goes through ``ConnectionProvider``.
No other module creates ``MailBox`` objects or calls ``login()`` directly.

One provider per account, obtained via ``get_provider()``.

Usage::

    provider = get_provider(account)

    async with provider.connection() as mb:
        mb.folder.set("INBOX")
        messages = list(mb.fetch(...))

The provider enforces a per-account concurrency cap, reuses idle
connections, retries on Gmail rate-limits with proper socket cleanup,
and guarantees no zombie TCP connections on failure.
"""

from __future__ import annotations

import asyncio
import socket as _socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from imap_tools import MailBox

from .config import AccountConfig
from .folders import discover_folders

log = structlog.get_logger()

DEFAULT_MAX_CONNS = 3
CONNECT_MAX_RETRIES = 4
CONNECT_RETRY_BASE = 5
CONNECT_MAX_BACKOFF = 60

# TCP keepalive: detect dead connections in ~90s (60 + 10*3) instead of
# waiting 10-30 min for the server-side timeout.  Without this, a network
# drop leaves zombie connections that Gmail still counts against the
# 15-connection limit.
_KEEPALIVE_IDLE = 60   # seconds before first probe
_KEEPALIVE_INTVL = 10  # seconds between probes
_KEEPALIVE_CNT = 3     # probes before declaring dead


# ── Socket cleanup ──────────────────────────────────────────────


def _enable_keepalive(sock: _socket.socket) -> None:
    """Enable TCP keepalive with aggressive probe intervals.

    After ``_KEEPALIVE_IDLE`` seconds of silence the OS sends probes every
    ``_KEEPALIVE_INTVL`` seconds.  After ``_KEEPALIVE_CNT`` failed probes
    the connection is torn down and the remote server releases the slot.

    Works on macOS (``TCP_KEEPALIVE``) and Linux (``TCP_KEEPIDLE`` +
    ``TCP_KEEPINTVL`` + ``TCP_KEEPCNT``).  On other platforms only the
    basic ``SO_KEEPALIVE`` flag is set (OS defaults apply).
    """
    try:
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
        if hasattr(_socket, "TCP_KEEPIDLE"):  # Linux
            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, _KEEPALIVE_IDLE)
            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, _KEEPALIVE_INTVL)
            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, _KEEPALIVE_CNT)
        elif hasattr(_socket, "TCP_KEEPALIVE"):  # macOS
            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPALIVE, _KEEPALIVE_IDLE)
    except OSError:
        pass


def force_close(mb: MailBox) -> None:
    """Kill the raw TCP socket.  No IMAP commands, no exceptions leaked.

    Safe to call from any thread.  A concurrent ``recv()`` in another
    thread will raise ``OSError`` immediately.
    """
    try:
        mb.client.sock.shutdown(_socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        mb.client.sock.close()
    except Exception:
        pass


# ── Folder cache ────────────────────────────────────────────────


class FolderCache:
    """TTL-based cache of discovered folder lists, keyed by account email."""

    def __init__(self, ttl: float = 300) -> None:
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._ttl = ttl

    def get(self, email: str) -> list[dict[str, Any]] | None:
        entry = self._cache.get(email)
        if entry and (time.monotonic() - entry[0]) < self._ttl:
            return list(entry[1])
        return None

    def put(self, email: str, folders: list[dict[str, Any]]) -> None:
        self._cache[email] = (time.monotonic(), folders)

    def invalidate(self, email: str) -> None:
        self._cache.pop(email, None)


_folder_cache = FolderCache()


async def get_or_discover_folders(
    mb: MailBox,
    account_email: str,
) -> list[dict[str, Any]]:
    """Return folders from cache, or discover them via *mb* and cache."""
    cached = _folder_cache.get(account_email)
    if cached is not None:
        return cached
    folders = await discover_folders(mb)
    _folder_cache.put(account_email, folders)
    return folders


# ── Connection provider ─────────────────────────────────────────


class ConnectionProvider:
    """Per-account IMAP connection pool with concurrency cap and idle reuse.

    ``connection()`` is the **only** public way to obtain a ``MailBox``.
    It is an async context manager that:

    1. Acquires a semaphore permit (blocks if ``max_conns`` are out).
    2. Pops an idle connection or creates a new one (with retry).
    3. Yields it for use.
    4. On normal exit, health-checks and returns it to the idle pool.
    5. On error, forcefully closes the socket (no zombies).
    6. Releases the semaphore permit in every case.
    """

    def __init__(
        self, account: AccountConfig, *, max_conns: int = DEFAULT_MAX_CONNS,
    ) -> None:
        self._account = account
        self._max_conns = max_conns
        self._sem = asyncio.Semaphore(max_conns)
        self._permits_out = 0
        self._idle: asyncio.Queue[MailBox] = asyncio.Queue(maxsize=max_conns)
        self._active: set[int] = set()
        self._closed = False

    # ── public API ──────────────────────────────────────────

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[MailBox]:
        """Borrow a connection.  Reuses idle ones, creates if needed."""
        await self._sem.acquire()
        self._permits_out += 1
        mb: MailBox | None = None
        try:
            mb = await self._get_or_create()
            self._active.add(id(mb))
            yield mb
        except BaseException:
            if mb is not None:
                self._active.discard(id(mb))
                self._destroy_sync(mb)
                mb = None
            raise
        finally:
            if mb is not None:
                self._active.discard(id(mb))
                self._return_or_destroy(mb)
            self._permits_out -= 1
            self._sem.release()

    def force_disconnect_all(self) -> None:
        """Kill every idle socket instantly (for shutdown / signal handler).

        Marks the provider as closed so returning connections are destroyed
        rather than recycled.  Active connections will fail on their next
        I/O operation, which the owning ``connection()`` context manager
        handles gracefully.
        """
        self._closed = True
        while not self._idle.empty():
            try:
                force_close(self._idle.get_nowait())
            except Exception:
                pass

    async def shutdown(self) -> None:
        """Drain the idle pool and mark the provider as closed."""
        self._closed = True
        self.force_disconnect_all()

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "active": len(self._active),
            "idle": self._idle.qsize(),
            "available_permits": self._max_conns - self._permits_out,
            "max_conns": self._max_conns,
        }

    # ── internals ───────────────────────────────────────────

    async def _get_or_create(self) -> MailBox:
        while not self._idle.empty():
            mb = self._idle.get_nowait()
            if await self._health_check(mb):
                return mb
            self._destroy_sync(mb)
        return await asyncio.to_thread(self._create_sync)

    def _create_sync(self) -> MailBox:
        """Blocking: open TCP + TLS + LOGIN with retry.

        Every failed attempt explicitly closes the socket so the
        remote server doesn't count zombie connections.
        """
        last_exc: Exception | None = None
        for attempt in range(CONNECT_MAX_RETRIES):
            mb = MailBox(self._account.imap_host, self._account.imap_port)
            try:
                mb.login(
                    self._account.email,
                    self._account.password.get_secret_value(),
                    initial_folder=None,
                )
                _enable_keepalive(mb.client.sock)
                return mb
            except Exception as exc:
                force_close(mb)
                last_exc = exc
                too_many = "Too many simultaneous connections" in str(exc)
                if too_many and attempt < CONNECT_MAX_RETRIES - 1:
                    delay = min(
                        CONNECT_RETRY_BASE * (2 ** attempt), CONNECT_MAX_BACKOFF,
                    )
                    log.warning(
                        "imap_conn_limit_retry",
                        account=self._account.email,
                        attempt=attempt + 1,
                        backoff_seconds=delay,
                    )
                    time.sleep(delay)
                    continue
                raise
        raise ConnectionError(
            f"IMAP connection limit for {self._account.email} "
            f"after {CONNECT_MAX_RETRIES} retries"
        ) from last_exc

    async def _health_check(self, mb: MailBox) -> bool:
        try:
            await asyncio.to_thread(mb.client.noop)
            return True
        except Exception:
            return False

    def _return_or_destroy(self, mb: MailBox) -> None:
        if not self._closed:
            try:
                self._idle.put_nowait(mb)
                return
            except asyncio.QueueFull:
                pass
        self._destroy_sync(mb)

    @staticmethod
    def _destroy_sync(mb: MailBox) -> None:
        try:
            mb.logout()
        except Exception:
            pass
        force_close(mb)


# ── Global provider registry ────────────────────────────────────

_providers: dict[tuple[int, str], ConnectionProvider] = {}


def get_provider(
    account: AccountConfig,
    *,
    max_conns: int = DEFAULT_MAX_CONNS,
) -> ConnectionProvider:
    """Return the singleton ``ConnectionProvider`` for *account*.

    Keyed by ``(event_loop_id, email)`` so test runners with separate
    event loops get independent providers.
    """
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, account.email)
    if key not in _providers or _providers[key]._closed:
        _providers[key] = ConnectionProvider(account, max_conns=max_conns)
    return _providers[key]
