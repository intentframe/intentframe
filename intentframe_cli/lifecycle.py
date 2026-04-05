"""Gateway process lifecycle — start, stop, wait.

  1. Start gateway as a subprocess
  2. Stop by calling POST /system/shutdown
  3. Wait up to SHUTDOWN_TIMEOUT, then force-kill
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from intentframe_cli.client import GatewayClient

logger = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 90.0
HEALTH_POLL_INTERVAL = 0.5


def _default_run_dir() -> Path:
    return Path(
        os.environ.get("INTENTFRAME_RUN_DIR", os.path.expanduser("~/.intentframe/run"))
    )


def _pid_file(run_dir: Path | None = None) -> Path:
    return (run_dir or _default_run_dir()) / "gateway.pid"


def read_gateway_pid(run_dir: Path | None = None) -> int | None:
    """Read the gateway PID from its PID file. Returns None if not found."""
    pf = _pid_file(run_dir)
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def is_running(run_dir: Path | None = None) -> bool:
    """Check if the gateway process is alive."""
    pid = read_gateway_pid(run_dir)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start_gateway(
    *,
    foreground: bool = False,
    socket_path: str | None = None,
) -> subprocess.Popen | None:
    """Start the gateway process.

    In foreground mode, replaces the current process (exec).
    In background mode, spawns a subprocess and returns the Popen handle.
    """
    if is_running():
        logger.debug("start_gateway: gateway already running")
        return None

    if foreground:
        os.execvp(
            sys.executable,
            [sys.executable, "-m", "intentframe_gateway.entry"],
        )
        return None

    run_dir = _default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(
        os.environ.get("INTENTFRAME_LOG_DIR", os.path.expanduser("~/.intentframe/logs"))
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "gateway.log", "a")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "intentframe_gateway.entry"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    log_file.close()
    logger.info("Gateway subprocess started (pid=%s)", proc.pid)
    return proc


async def wait_for_gateway(
    client: GatewayClient,
    *,
    timeout: float = 60.0,
) -> bool:
    """Poll the gateway socket until healthy or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.socket_exists:
            try:
                resp = await client.get("/health")
                if resp.status_code == 200:
                    return True
            except Exception as exc:
                logger.debug("wait_for_gateway: health check error: %s", exc)
        await asyncio.sleep(HEALTH_POLL_INTERVAL)
    logger.warning("wait_for_gateway: timed out after %.1fs", timeout)
    return False


async def restart_gateway(
    client: GatewayClient,
    *,
    shutdown_timeout: float = SHUTDOWN_TIMEOUT,
    startup_timeout: float = 120.0,
) -> bool:
    """Stop the gateway, start a fresh process, and wait for it.

    Returns True if the new gateway became healthy.
    """
    await stop_gateway(client, timeout=shutdown_timeout)
    proc = start_gateway()
    if proc is None and not is_running():
        logger.error("restart_gateway: failed to start new gateway process")
        return False
    return await wait_for_gateway(client, timeout=startup_timeout)


async def stop_gateway(
    client: GatewayClient,
    *,
    timeout: float = SHUTDOWN_TIMEOUT,
) -> bool:
    """Gracefully stop the gateway via its shutdown API.

    1. Send POST /system/shutdown (short timeout -- just delivers SIGTERM)
    2. Wait up to ``timeout`` seconds for the process to exit
    3. Force-kill via PID if it doesn't exit in time

    A second KeyboardInterrupt during the wait will force-kill immediately.

    Returns True if the gateway stopped gracefully,
    False if it had to be force-killed.
    """
    pid = read_gateway_pid()

    try:
        await asyncio.wait_for(client.shutdown(), timeout=3.0)
    except Exception:
        pass

    try:
        await client.close()
    except Exception:
        pass

    if pid is None:
        return True

    return await _wait_for_pid_exit(pid, timeout)


async def _wait_for_pid_exit(pid: int, timeout: float) -> bool:
    """Poll until the process exits. Force-kills on timeout or second Ctrl+C."""
    from intentframe_cli.ui import console

    deadline = time.monotonic() + timeout
    interval = 0
    while time.monotonic() < deadline:
        try:
            waited, _ = os.waitpid(pid, os.WNOHANG)
            if waited != 0:
                return True
        except ChildProcessError:
            pass

        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return True

        interval += 1
        if interval == 4:
            console.print(
                f"[dim]  Waiting for gateway (pid {pid}) to exit… "
                f"(Ctrl+C to force-kill)[/]"
            )

        try:
            await asyncio.sleep(0.5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("[yellow]  Force-killing gateway...[/]")
            _force_kill(pid)
            return False

    logger.warning("stop_gateway: pid %s did not exit in %.1fs; SIGKILL", pid, timeout)
    _force_kill(pid)
    return False


def _force_kill(pid: int) -> None:
    """Send SIGKILL to the process group rooted at pid."""
    try:
        os.killpg(pid, signal.SIGKILL)
        logger.info("Sent SIGKILL to process group %s", pid)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
            logger.info("Sent SIGKILL to process %s", pid)
        except (ProcessLookupError, PermissionError):
            logger.debug("force_kill: process %s already gone", pid)
