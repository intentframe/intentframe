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

Profile selection:
  ``--profile root`` asks the CLI to spawn the gateway with the root
  profile (root-scoped policy + ``jarvis_pa/executor_root.yaml``).  The
  flag is translated into two environment variables the gateway and
  supervisor already understand:

    INTENTFRAME_PROFILE=root
    EXECUTOR_CONFIG=jarvis_pa/executor_root.yaml   (only when unset)

  The flag is only effective when the CLI actually spawns the gateway.
  If a gateway is already running, the flag is ignored (with a warning)
  — restart is required to change profile.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from intentframe_cli.client import GatewayClient
from intentframe_cli.lifecycle import (
    is_running,
    start_gateway,
    wait_for_gateway,
)
from intentframe_cli.repl import run_normal_mode, run_setup_mode
from intentframe_cli.ui import console, error, root_demo_installed

_PROFILE_CHOICES = ("user", "root")
_ROOT_EXECUTOR_CONFIG = "jarvis_pa/executor_root.yaml"


def _warn_if_root_demo_missing(profile: str | None) -> None:
    """Yellow warning when ``--profile root`` is requested on a machine
    that hasn't run ``intentframe_setup_root_demo.sh`` yet.

    The gateway will still start, the executor will still come up, and
    policy will still match the root profile shape.  What *won't*
    happen is the ``sudo -n sandbox-exec`` wrap -- RUN_COMMAND will
    run unprivileged, which is almost certainly not what the operator
    wanted when they passed ``--profile root``.  Warn loudly but do
    not block.
    """
    if profile != "root":
        return
    if root_demo_installed():
        return
    console.print(
        "[yellow]--profile root requested but root-demo is not "
        "installed on this machine.  RUN_COMMAND will execute "
        "unprivileged.[/]"
    )
    console.print(
        "[dim]Install with:  sudo bash intentframe_setup_root_demo.sh[/]"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="intentframe-gateway-cli",
        description="Interactive CLI frontend for IntentFrame.",
    )
    parser.add_argument(
        "--profile",
        choices=_PROFILE_CHOICES,
        default=None,
        help=(
            "Profile to spawn the gateway under.  'user' (default) seeds "
            "home-scoped policy and uses jarvis_pa/executor.yaml.  'root' "
            "seeds root-scoped policy and uses jarvis_pa/executor_root.yaml. "
            "Ignored if a gateway is already running."
        ),
    )
    return parser.parse_args(argv)


def _apply_profile_env(profile: str | None) -> None:
    """Translate ``--profile`` into env vars the gateway already consumes.

    * ``INTENTFRAME_PROFILE`` is always set when a profile is given; the
      gateway's bootstrap reads it to pick the right policy and
      workspace shape.
    * ``EXECUTOR_CONFIG`` is only set for ``--profile root`` and only
      when the operator has not already set it explicitly — never
      override an explicit override.
    """
    if profile is None:
        return
    os.environ["INTENTFRAME_PROFILE"] = profile
    if profile == "root" and not os.environ.get("EXECUTOR_CONFIG"):
        os.environ["EXECUTOR_CONFIG"] = _ROOT_EXECUTOR_CONFIG


async def _async_main(profile: str | None = None) -> None:
    client = GatewayClient()

    if not is_running():
        _apply_profile_env(profile)
        _warn_if_root_demo_missing(profile)
        label = f" ({profile} profile)" if profile else ""
        console.print(f"[bold cyan]Starting IntentFrame gateway{label}...[/]")
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
        if profile is not None:
            console.print(
                "[yellow]Gateway is already running — --profile is ignored.  "
                "Run 'quit' inside the CLI and relaunch to change profile.[/]"
            )
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
    args = _parse_args()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(_async_main(args.profile))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
