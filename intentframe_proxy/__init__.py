"""Shared HTTP→UDS proxy primitives.

``UDSProxy`` and ``proxy_websocket`` are the canonical implementations;
both ``intentframe_gateway`` and ``intentframe_edge`` import from here.
"""

from intentframe_proxy.proxy import UDSProxy, proxy_websocket

__all__ = ["UDSProxy", "proxy_websocket"]
