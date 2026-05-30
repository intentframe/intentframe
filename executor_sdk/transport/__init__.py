"""
Transport layer -- how execution requests arrive at the executor.

The transport is a pluggable pipe: it receives bytes over a specific
protocol, deserializes them, calls the gateway handler, and sends
the serialized response back. The gateway never knows which transport
delivered the request.

Platform-specific implementations register themselves via
register_transport() and are instantiated at startup from config.

Implementations to create later:
    - unix_socket.py  (device default -- same-machine IPC)
    - grpc_server.py  (cloud/device -- high-perf cross-machine)
    - rest_server.py  (admin/debug -- simple HTTP)
"""

from __future__ import annotations

from typing import Any

from executor_sdk.exceptions import ConfigurationError
from executor_sdk.transport.base import TransportServer

__all__ = ["TransportServer", "register_transport", "create_transport"]

# ─── Plugin Registry ─────────────────────────────────────────────────────────

_TRANSPORT_REGISTRY: dict[str, type[TransportServer]] = {}


def register_transport(
    transport_type: str, transport_class: type[TransportServer]
) -> None:
    """Register a transport implementation for config-driven instantiation.

    Platform-specific transport modules call this at import time:
        register_transport("unix_socket", UnixSocketTransport)
    """
    _TRANSPORT_REGISTRY[transport_type] = transport_class


def create_transport(config: Any) -> TransportServer:
    """Instantiate the configured transport from the registry.

    Args:
        config: Transport section of executor.yaml.

    Returns:
        Configured TransportServer instance ready to start().

    Raises:
        ConfigurationError: If the transport type is not registered.
    """
    transport_class = _TRANSPORT_REGISTRY.get(config.type)
    if transport_class is None:
        registered = ", ".join(sorted(_TRANSPORT_REGISTRY)) or "(none)"
        raise ConfigurationError(
            f"Unknown transport type: '{config.type}'. "
            f"Registered transports: {registered}",
        )
    return transport_class(**config.options)
