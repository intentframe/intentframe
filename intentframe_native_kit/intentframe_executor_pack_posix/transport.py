"""
Unix domain socket transport for POSIX (macOS / Linux / container) deployments.

Uses asyncio's built-in Unix socket server. The wire protocol is
simple length-prefixed JSON:
    [4 bytes: message length (big-endian uint32)] [N bytes: JSON payload]

This transport is suitable for same-machine IPC between the local
Guardian (or any authorized caller) and the executor service.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from pathlib import Path

from executor_sdk.constants import DEFAULT_UNIX_SOCKET_PATH
from executor_sdk.models import ExecutionRequest, ExecutionResult
from executor_sdk.transport.base import RequestHandler, TransportServer

logger = logging.getLogger(__name__)

# 4-byte big-endian unsigned int for message length framing
_HEADER_FORMAT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)
_MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB safety limit


class UnixSocketTransport(TransportServer):
    """Unix domain socket transport implementation.

    Listens on a Unix socket file. Each connection can send multiple
    request/response pairs (persistent connection). Length-prefixed
    JSON framing ensures message boundaries are preserved.
    """

    def __init__(self, socket_path: str = DEFAULT_UNIX_SOCKET_PATH, **_kwargs) -> None:
        self._socket_path = Path(socket_path)
        self._server: asyncio.Server | None = None
        self._running = False
        self._handler: RequestHandler | None = None

    async def start(self, handler: RequestHandler) -> None:
        """Start listening on the Unix socket."""
        self._handler = handler
        self._running = True

        # Ensure parent directory exists
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale socket from previous run
        self._socket_path.unlink(missing_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self._socket_path),
        )

        logger.info("Unix socket transport listening: %s", self._socket_path)

        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the Unix socket server."""
        self._running = False
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Clean up socket file
        self._socket_path.unlink(missing_ok=True)
        logger.info("Unix socket transport stopped")

    def is_running(self) -> bool:
        return self._running

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection (may send multiple requests)."""
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug("Client connected: %s", peer)

        try:
            while self._running:
                # ── Read request ──────────────────────────────────────
                request = await self._read_message(reader)
                if request is None:
                    break  # Client disconnected

                # ── Deserialize ───────────────────────────────────────
                try:
                    exec_request = ExecutionRequest.model_validate_json(request)
                except Exception as exc:
                    error_result = ExecutionResult(
                        success=False,
                        error=f"Invalid request: {exc}",
                    )
                    await self._write_message(writer, error_result.model_dump_json().encode())
                    continue

                # ── Handle ────────────────────────────────────────────
                result = await self._handler(exec_request)

                # ── Serialize and respond ─────────────────────────────
                response_data = result.model_dump_json().encode()
                await self._write_message(writer, response_data)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Client handler error: %s", exc, exc_info=True)
        finally:
            writer.close()
            await writer.wait_closed()
            logger.debug("Client disconnected: %s", peer)

    @staticmethod
    async def _read_message(reader: asyncio.StreamReader) -> bytes | None:
        """Read a length-prefixed message. Returns None on disconnect."""
        try:
            header = await reader.readexactly(_HEADER_SIZE)
        except asyncio.IncompleteReadError:
            return None

        (length,) = struct.unpack(_HEADER_FORMAT, header)

        if length > _MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {length} bytes")

        return await reader.readexactly(length)

    @staticmethod
    async def _write_message(writer: asyncio.StreamWriter, data: bytes) -> None:
        """Write a length-prefixed message."""
        header = struct.pack(_HEADER_FORMAT, len(data))
        writer.write(header + data)
        await writer.drain()
