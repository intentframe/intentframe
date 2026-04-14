"""Process manager for gateway-managed services.

Manages process types that are NOT part of the supervisor:
  - credential-vault   (uvicorn on UDS, has /health)
  - jarvis             (uvicorn on UDS, has /health)
  - edi                (long-running async daemon, PID file lifecycle)
  - telegram           (long-running polling bot, no socket)
  - platform-server    (macOS only, launched via ``open`` for TCC permissions)
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
from typing import Any

from supervisor.health import wait_for_health

from intentframe_gateway.config import GatewayConfig

logger = logging.getLogger(__name__)


class ManagedProcess:
    """Tracks a single managed subprocess."""

    __slots__ = ("name", "process", "socket_path", "healthy", "restart_count", "started_at")

    def __init__(
        self,
        name: str,
        process: subprocess.Popen,
        socket_path: Path | None = None,
    ) -> None:
        self.name = name
        self.process = process
        self.socket_path = socket_path
        self.healthy = False
        self.restart_count = 0
        self.started_at = time.monotonic()


class ProcessManager:
    """Manages gateway-owned processes outside the supervisor."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._processes: dict[str, ManagedProcess] = {}

    # ── Vault ──────────────────────────────────────────────────────

    async def start_vault(self) -> bool:
        """Start the credential vault and wait for it to become healthy."""
        socket_path = self._config.socket_path(self._config.vault_socket_name)
        return await self._start_uvicorn(
            name="credential-vault",
            module="intentframe_credentials.server:app",
            socket_path=socket_path,
        )

    # ── Jarvis ─────────────────────────────────────────────────────

    async def start_jarvis(self, *, env: dict[str, str] | None = None) -> bool:
        """Start Jarvis and wait for it to become healthy."""
        socket_path = self._config.socket_path("jarvis.sock")
        return await self._start_uvicorn(
            name="jarvis",
            module="jarvis.server.app:app",
            socket_path=socket_path,
            extra_env=env,
            startup_timeout=90.0,
        )

    # ── EDI ────────────────────────────────────────────────────────

    async def start_edi(self) -> bool:
        """Start the EDI email sync daemon (fire-and-forget).

        Returns True if the process was spawned. Does not wait for
        sync to complete — the daemon manages its own lifecycle via
        PID file and signal handlers.
        """
        log_path = self._config.log_dir / "edi.log"
        self._config.log_dir.mkdir(parents=True, exist_ok=True)

        log_file = open(log_path, "a")
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "external_data_ingestion.email", "start"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except Exception as exc:
            logger.error("Failed to start EDI daemon: %s", exc)
            log_file.close()
            return False
        log_file.close()

        self._processes["edi"] = ManagedProcess(
            name="edi", process=process,
        )
        logger.info("EDI daemon spawned (pid=%d)", process.pid)
        return True

    # ── Platform Server (macOS only) ─────────────────────────────

    async def start_platform_server(self) -> bool:
        """Launch the Swift platform server via ``open`` on macOS.

        Uses ``open`` so macOS treats it as a standalone app with its
        own TCC identity — required for Calendar/Contacts/Reminders
        permission prompts.  The process is *not* a child of the
        gateway; we just wait for ``platform.sock`` to become healthy.

        Returns True once the server is reachable, False on timeout.
        """
        if sys.platform != "darwin":
            logger.info("Platform server skipped (not macOS)")
            return False

        socket_path = self._config.socket_path(
            self._config.platform_socket_name,
        )

        already_healthy = await wait_for_health(
            socket_path=socket_path,
            health_path="/health",
            timeout=2.0,
            service_name="platform-server",
        )
        if already_healthy:
            logger.info("Platform server already running")
            return True

        app_path = self._find_platform_app()
        if app_path is None:
            logger.error(
                "Cannot find macos-appkit-server.app — "
                "set PLATFORM_SERVER_APP or run macos-appkit-server/Scripts/bundle.sh"
            )
            return False

        logger.info("Opening platform server: %s", app_path)
        result = subprocess.run(
            ["open", str(app_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("open failed: %s", result.stderr.strip())
            return False

        healthy = await wait_for_health(
            socket_path=socket_path,
            health_path="/health",
            timeout=15.0,
            service_name="platform-server",
        )
        if healthy:
            logger.info("Platform server healthy (socket=%s)", socket_path)
        else:
            logger.error("Platform server did not become healthy in time")
        return healthy

    @staticmethod
    def _find_platform_app() -> Path | None:
        """Locate the macos-appkit-server.app bundle."""
        from_env = os.environ.get("PLATFORM_SERVER_APP")
        if from_env:
            p = Path(from_env)
            if p.exists():
                return p

        candidates = [
            Path(__file__).resolve().parents[1]
            / "macos-appkit-server" / ".build" / "release" / "macos-appkit-server.app",
            Path.home() / "Library" / "IntentFrame" / "macos-appkit-server.app",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    # ── Telegram ───────────────────────────────────────────────────

    async def start_telegram(self, *, env: dict[str, str] | None = None) -> bool:
        """Start the Jarvis Telegram bot."""
        log_path = self._config.log_dir / "telegram.log"
        self._config.log_dir.mkdir(parents=True, exist_ok=True)

        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if env:
            child_env.update(env)
        jarvis_sock = str(self._config.socket_path("jarvis.sock"))
        child_env["JARVIS_TELEGRAM_JARVIS_SOCKET_PATH"] = jarvis_sock

        log_file = open(log_path, "a")
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "jarvis_telegram"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=child_env,
            )
        except Exception as exc:
            logger.error("Failed to start Telegram bot: %s", exc)
            log_file.close()
            return False
        log_file.close()

        self._processes["telegram"] = ManagedProcess(
            name="telegram", process=process,
        )
        logger.info("Telegram bot spawned (pid=%d)", process.pid)
        return True

    # ── Generic lifecycle ──────────────────────────────────────────

    async def stop(self, name: str, *, timeout: float = 10.0) -> None:
        """Stop a managed process by name.

        EDI is special: its `python -m ... start` is a wrapper that exits
        as soon as the async daemon finishes (same process) — but when
        the gateway restarts against an already-running daemon, the
        wrapper exited with code 1 and the real daemon keeps running
        detached from our Popen. Signal the real daemon via its PID file.
        """
        proc = self._processes.pop(name, None)

        if name == "edi":
            await self._stop_edi_daemon(timeout)
            return

        if proc is None:
            return
        if proc.process.poll() is not None:
            return

        logger.info("Stopping %s (pid=%d)", name, proc.process.pid)
        proc.process.terminate()
        try:
            proc.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Force killing %s", name)
            proc.process.kill()
            proc.process.wait()

        if proc.socket_path:
            proc.socket_path.unlink(missing_ok=True)

    async def _stop_edi_daemon(self, timeout: float) -> None:
        """SIGTERM the EDI daemon via its PID file, then verify it exits."""
        alive, pid = self._edi_daemon_status()
        if not alive or pid is None:
            return
        logger.info("Stopping edi daemon (pid=%d)", pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            alive, _ = self._edi_daemon_status()
            if not alive:
                return
            await asyncio.sleep(0.2)
        logger.warning("EDI daemon did not exit after SIGTERM; sending SIGKILL")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _edi_daemon_status(self) -> tuple[bool, int | None]:
        """Probe EDI's daemon via its PID file. Mirrors EDI's own
        is_daemon_running() logic so the two agree.
        """
        pid_file = Path(
            os.environ.get(
                "INTENTFRAME_EMAIL_HOME",
                os.path.expanduser("~/.intentframe/email"),
            )
        ) / "daemon.pid"
        if not pid_file.exists():
            return False, None
        try:
            pid = int(pid_file.read_text().strip())
        except (ValueError, OSError):
            return False, None
        try:
            os.kill(pid, 0)
            return True, pid
        except ProcessLookupError:
            return False, None
        except PermissionError:
            # Process exists under a different uid — count as alive.
            return True, pid

    async def stop_all(self) -> None:
        """Stop all managed processes in reverse insertion order."""
        for name in reversed(list(self._processes)):
            await self.stop(name)

    def status(self, name: str) -> dict[str, Any]:
        """Return status dict for a managed process.

        EDI uses a PID-file lifecycle (daemon detaches from our wrapper
        Popen), so its liveness is determined by its own PID file, not
        by the wrapper's exit code.
        """
        if name == "edi":
            alive, pid = self._edi_daemon_status()
            proc = self._processes.get(name)
            uptime = 0.0
            if alive and proc is not None:
                uptime = time.monotonic() - proc.started_at
            return {
                "name": "edi",
                "running": alive,
                "pid": pid,
                "healthy": alive,
                "restarts": proc.restart_count if proc else 0,
                "uptime": uptime,
            }

        proc = self._processes.get(name)
        if proc is None:
            return {"name": name, "running": False, "pid": None}
        running = proc.process.poll() is None
        healthy = proc.healthy if proc.socket_path else running
        return {
            "name": name,
            "running": running,
            "pid": proc.process.pid,
            "healthy": healthy,
            "restarts": proc.restart_count,
            "uptime": time.monotonic() - proc.started_at if running else 0,
        }

    _KNOWN_SERVICES = ("credential-vault", "jarvis", "edi", "telegram")

    def all_status(self) -> dict[str, dict[str, Any]]:
        """Return status for every known managed service (including unstarted ones)."""
        names = dict.fromkeys(self._KNOWN_SERVICES)
        names.update(dict.fromkeys(self._processes))
        return {name: self.status(name) for name in names}

    # ── Internal helpers ───────────────────────────────────────────

    async def _start_uvicorn(
        self,
        name: str,
        module: str,
        socket_path: Path,
        *,
        extra_env: dict[str, str] | None = None,
        startup_timeout: float = 30.0,
    ) -> bool:
        """Start a uvicorn service on a UDS and wait for /health."""
        socket_path.unlink(missing_ok=True)
        log_path = self._config.log_dir / f"{name}.log"
        self._config.log_dir.mkdir(parents=True, exist_ok=True)
        self._config.run_dir.mkdir(parents=True, exist_ok=True)

        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if extra_env:
            child_env.update(extra_env)

        log_file = open(log_path, "a")
        process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                module,
                "--uds", str(socket_path),
                "--log-level", "info",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=child_env,
        )
        log_file.close()

        managed = ManagedProcess(name=name, process=process, socket_path=socket_path)
        self._processes[name] = managed

        healthy = await wait_for_health(
            socket_path=socket_path,
            health_path="/health",
            timeout=startup_timeout,
            service_name=name,
        )
        managed.healthy = healthy

        if healthy:
            logger.info("%s started (pid=%d, socket=%s)", name, process.pid, socket_path)
        else:
            logger.error("%s failed to become healthy", name)
            process.terminate()

        return healthy
