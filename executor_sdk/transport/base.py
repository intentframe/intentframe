"""
Abstract base class for transport layer implementations.

A transport server is responsible for:
    1. Listening for inbound connections on its protocol
    2. Deserializing raw bytes into ExecutionRequest
    3. Calling the gateway handler with the ExecutionRequest
    4. Serializing the ExecutionResult back to wire format
    5. Sending the response

The transport does NOT perform auth verification, validation, or
routing. It's a pure I/O pipe. The handler callback (injected by
the gateway via start()) does all the real work.

Implementations:
    Each platform/deployment provides one concrete transport.
    Only ONE transport is active per executor instance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from executor_sdk.models import ExecutionRequest, ExecutionResult

# Type alias for the handler the gateway injects into the transport.
# Transport calls this for every valid inbound request.
RequestHandler = Callable[[ExecutionRequest], Awaitable[ExecutionResult]]


class TransportServer(ABC):
    """Abstract base for all transport implementations.

    Lifecycle:
        transport = SomeTransport(**options)
        await transport.start(gateway.handle)   # begins listening
        ...
        await transport.stop()                  # graceful shutdown

    Contract:
        - start() blocks until stop() is called or the server crashes.
        - The handler MUST be called for every well-formed inbound request.
        - Malformed requests (can't even deserialize) are rejected at the
          transport level with an appropriate protocol-level error.
        - The transport MUST NOT swallow exceptions from the handler.
    """

    @abstractmethod
    async def start(self, handler: RequestHandler) -> None:
        """Start the transport server and begin accepting requests.

        Args:
            handler: Async callable that processes each ExecutionRequest
                     and returns an ExecutionResult. Provided by the gateway.

        This method should run until stop() is called.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the transport server.

        Should:
            - Stop accepting new connections
            - Wait for in-flight requests to complete (up to shutdown timeout)
            - Release all resources (sockets, ports, etc.)
        """
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the transport is currently accepting requests."""
        ...
