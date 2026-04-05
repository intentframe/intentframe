"""Interactive CLI frontend for IntentFrame.

Starts the gateway (if not already running), connects via UDS, and
provides a two-mode REPL:

  Setup mode (partial startup -- missing OpenAI key):
    Only vault, health, status, logs, help, quit are available.
    After storing the mandatory key the gateway auto-restarts and
    transitions to normal mode.

  Normal mode (full startup):
    Chat with Jarvis (default), manage services, credentials,
    EDI accounts, app preferences, audit, policies, and more.
"""

from __future__ import annotations

import asyncio
import logging

from intentframe_cli.client import GatewayClient
from intentframe_cli.lifecycle import (
    is_running,
    start_gateway,
    wait_for_gateway,
)
from intentframe_cli.repl import run_normal_mode, run_setup_mode
from intentframe_cli.ui import console, error


async def _async_main() -> None:
    client = GatewayClient()

    if not is_running():
        console.print("[bold cyan]Starting IntentFrame gateway...[/]")
        proc = start_gateway()
        if proc is None and not is_running():
            error("Failed to start gateway.")
            return

        console.print("[dim]Waiting for gateway to become healthy...[/]")
        healthy = await wait_for_gateway(client, timeout=120.0)
        if not healthy:
            error("Gateway did not become healthy in time.")
            console.print("[dim]Check ~/.intentframe/logs/gateway.log for details.[/]")
            await client.close()
            return
    else:
        console.print("[dim]Connecting to running IntentFrame gateway...[/]")

    try:
        h = await client.health()
    except Exception:
        error("Could not reach gateway. Check ~/.intentframe/logs/gateway.log")
        await client.close()
        return

    try:
        if h.get("partial_startup", False):
            user_quit = await run_setup_mode(client, h)
            if user_quit:
                return
            h = await client.health()

        await run_normal_mode(client, h)
    finally:
        await client.close()


def main() -> None:
    """Entry point for the ``intentframe-gateway-cli`` console script."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
