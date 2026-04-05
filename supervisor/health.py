"""
Health Check Polling.

Polls each service's /health endpoint over UDS until healthy or timeout.
Used by the supervisor during startup sequencing and ongoing monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


async def wait_for_health(
    socket_path: Path,
    health_path: str = "/health",
    timeout: float = 30.0,
    interval: float = 0.5,
    service_name: str = "service",
) -> bool:
    """Poll a service's health endpoint until it responds 200 or timeout.

    Args:
        socket_path: Path to the Unix Domain Socket.
        health_path: HTTP path to the health endpoint.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        service_name: Human-readable name for logging.

    Returns:
        True if the service became healthy, False on timeout.
    """
    deadline = time.monotonic() + timeout
    transport = httpx.AsyncHTTPTransport(uds=str(socket_path))

    async with httpx.AsyncClient(
        transport=transport,
        base_url=f"http://{service_name}",
        timeout=5.0,
    ) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(health_path)
                if resp.status_code == 200:
                    logger.info("%s is healthy", service_name)
                    return True
            except (httpx.ConnectError, httpx.ReadError, OSError):
                pass

            remaining = deadline - time.monotonic()
            await asyncio.sleep(min(interval, max(remaining, 0)))

    logger.error("%s failed health check after %.1fs", service_name, timeout)
    return False


async def check_health(
    socket_path: Path,
    health_path: str = "/health",
    service_name: str = "service",
) -> bool:
    """Single health check (non-blocking, no retry).

    Returns True if healthy, False otherwise.
    """
    transport = httpx.AsyncHTTPTransport(uds=str(socket_path))
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=f"http://{service_name}",
            timeout=5.0,
        ) as client:
            resp = await client.get(health_path)
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.ReadError, OSError):
        return False
