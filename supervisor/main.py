"""
IntentFrame Supervisor -- manages infra services.

Spawns the services listed in the active service-graph profile (in dependency
order), waits for health, monitors child processes, and handles graceful
shutdown. The graph is admin-owned data, not supervisor logic: it is selected
via ``--config`` / ``INTENTFRAME_SUPERVISOR_CONFIG``, defaulting to the packaged
``supervisor/config/supervisor.yaml`` (policy-registry, executor,
intentframe-server -- no resource-registry). First-party products and the test
stacks opt into the registry by pointing at
``intentframe_native_kit/supervisor_profile.yaml``.

The gateway starts the supervisor as a subprocess and passes runtime_env
credentials (e.g. OPENAI_API_KEY) via the parent process environment.
The supervisor propagates these into every child.

Usage (standalone, for development):
    python -m supervisor.main start
    python -m supervisor.main stop
    python -m supervisor.main status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from supervisor.config import (
    ServiceConfig,
    SupervisorConfig,
    load_supervisor_config,
)
from supervisor.health import check_health, wait_for_health

logger = logging.getLogger("supervisor")

# When running as a backend binary spawned by a native frontend,
# emit JSON progress events to stdout so the frontend can show startup progress.
_FRONTEND_MODE = os.environ.get("INTENTFRAME_FRONTEND_MODE") == "1"


def _emit(event: dict[str, Any]) -> None:
    """Write a JSON progress event to stdout for the native frontend."""
    if _FRONTEND_MODE:
        print(json.dumps(event), flush=True)


class ServiceProcess:
    """Tracks a spawned service subprocess."""

    def __init__(self, config: ServiceConfig, process: subprocess.Popen, socket_path: Path) -> None:
        self.config = config
        self.process = process
        self.socket_path = socket_path
        self.restart_count = 0
        self.started_at = time.monotonic()
        self.healthy = False


class Supervisor:
    """Process manager for IntentFrame infra services."""

    def __init__(
        self,
        config: SupervisorConfig,
        runtime_env: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self._runtime_env = runtime_env or {}
        self._services: dict[str, ServiceProcess] = {}
        self._shutdown_event = asyncio.Event()
        self._healthy_count: int = 0
        self._pid_file = config.run_dir / "supervisor.pid"

    async def start_all(self) -> bool:
        """Spawn all services in dependency order and wait for health.

        Returns True if all services started successfully.
        """
        self.config.run_dir.mkdir(parents=True, exist_ok=True)
        self.config.log_dir.mkdir(parents=True, exist_ok=True)

        self._kill_stale_supervisor()
        self._write_pid_file()
        self._clean_stale_sockets()

        total = len(self.config.services)
        self._healthy_count = 0

        layers = self._resolve_startup_order()

        for layer in layers:
            tasks = [self._start_service(svc, total) for svc in layer]
            results = await asyncio.gather(*tasks)

            if not all(results):
                failed = [
                    svc.name for svc, ok in zip(layer, results) if not ok
                ]
                logger.error("Services failed to start: %s", failed)
                _emit({"type": "failed", "services": failed})
                return False

        logger.info("All %d services started and healthy", len(self.config.services))
        _emit({
            "type": "ready",
            "run_dir": str(self.config.run_dir),
            "log_dir": str(self.config.log_dir),
            "total": total,
        })
        return True

    async def _start_service(self, svc_config: ServiceConfig, total: int) -> bool:
        """Spawn a single service and wait for it to become healthy."""
        socket_path = self.config.run_dir / svc_config.socket_name
        log_path = self.config.log_dir / f"{svc_config.name}.log"

        # Clean stale socket
        socket_path.unlink(missing_ok=True)

        logger.info("Starting %s ...", svc_config.name)
        _emit({"type": "starting", "service": svc_config.name, "done": self._healthy_count, "total": total})

        log_file = open(log_path, "a")
        child_env = {**os.environ, "PYTHONUNBUFFERED": "1", **self._runtime_env}
        process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                svc_config.module,
                "--uds", str(socket_path),
                "--log-level", "info",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=child_env,
        )

        svc = ServiceProcess(svc_config, process, socket_path)
        self._services[svc_config.name] = svc

        healthy = await wait_for_health(
            socket_path=socket_path,
            health_path=svc_config.health_path,
            timeout=svc_config.startup_timeout,
            service_name=svc_config.name,
        )
        svc.healthy = healthy

        if healthy:
            self._healthy_count += 1
            logger.info(
                "%s started (pid=%d, socket=%s)",
                svc_config.name, process.pid, socket_path,
            )
            _emit({"type": "healthy", "service": svc_config.name, "done": self._healthy_count, "total": total})
        else:
            logger.error("%s failed to become healthy", svc_config.name)
            _emit({"type": "unhealthy", "service": svc_config.name, "done": self._healthy_count, "total": total})
            process.terminate()

        return healthy

    async def monitor(self) -> None:
        """Monitor running services and restart crashed ones."""
        while not self._shutdown_event.is_set():
            for name, svc in list(self._services.items()):
                ret = svc.process.poll()
                if ret is not None:
                    logger.warning(
                        "%s exited with code %d", name, ret,
                    )
                    if (
                        svc.config.restart_on_crash
                        and svc.restart_count < svc.config.max_restarts
                        and not self._shutdown_event.is_set()
                    ):
                        svc.restart_count += 1
                        logger.info(
                            "Restarting %s (attempt %d/%d)",
                            name, svc.restart_count, svc.config.max_restarts,
                        )
                        total = len(self.config.services)
                        ok = await self._start_service(svc.config, total)
                        if ok:
                            self._services[name].restart_count = svc.restart_count

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=self.config.health_interval,
                )
                break
            except asyncio.TimeoutError:
                pass

    async def stop_all(self) -> None:
        """Gracefully stop all services."""
        self._shutdown_event.set()

        # Stop in reverse startup order
        for name in reversed(list(self._services)):
            svc = self._services[name]
            if svc.process.poll() is None:
                logger.info("Stopping %s (pid=%d)", name, svc.process.pid)
                svc.process.terminate()
                try:
                    svc.process.wait(timeout=self.config.graceful_shutdown_timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("Force killing %s", name)
                    svc.process.kill()
                    svc.process.wait()

        # Clean up sockets
        for name, svc in self._services.items():
            svc.socket_path.unlink(missing_ok=True)

        self._services.clear()
        self._remove_pid_file()
        logger.info("All services stopped")

    def _resolve_startup_order(self) -> list[list[ServiceConfig]]:
        """Topological sort of services by depends_on."""
        by_name = {s.name: s for s in self.config.services}
        started: set[str] = set()
        layers: list[list[ServiceConfig]] = []

        remaining = set(by_name)
        while remaining:
            layer = [
                by_name[name] for name in remaining
                if all(dep in started for dep in by_name[name].depends_on)
            ]
            if not layer:
                raise RuntimeError(
                    f"Circular dependency: {remaining}"
                )
            layers.append(layer)
            for svc in layer:
                started.add(svc.name)
                remaining.discard(svc.name)

        return layers

    def _write_pid_file(self) -> None:
        """Write current PID to run_dir/supervisor.pid."""
        self._pid_file.write_text(str(os.getpid()))

    def _remove_pid_file(self) -> None:
        self._pid_file.unlink(missing_ok=True)

    def _kill_stale_supervisor(self) -> None:
        """If a previous supervisor PID file exists, kill that process group."""
        if not self._pid_file.exists():
            return
        try:
            old_pid = int(self._pid_file.read_text().strip())
        except (ValueError, OSError):
            self._pid_file.unlink(missing_ok=True)
            return

        if old_pid == os.getpid():
            return

        # Kill the entire process group rooted at the old supervisor
        try:
            os.killpg(old_pid, signal.SIGTERM)
            logger.info("Killed stale supervisor process group (pgid=%d)", old_pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("No permission to kill stale pgid %d", old_pid)
        self._pid_file.unlink(missing_ok=True)

    def _clean_stale_sockets(self) -> None:
        """Remove leftover socket files from previous runs."""
        for svc in self.config.services:
            sock = self.config.run_dir / svc.socket_name
            sock.unlink(missing_ok=True)

    def get_status(self) -> dict[str, dict[str, Any]]:
        """Return status of all managed services."""
        status = {}
        for name, svc in self._services.items():
            running = svc.process.poll() is None
            status[name] = {
                "pid": svc.process.pid,
                "running": running,
                "healthy": svc.healthy,
                "restarts": svc.restart_count,
                "socket": str(svc.socket_path),
                "uptime": time.monotonic() - svc.started_at if running else 0,
            }
        return status


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


async def _cmd_start(config: SupervisorConfig) -> None:
    """Start all services and monitor them."""
    supervisor = Supervisor(config)

    # Wire shutdown signals
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("Shutdown signal received")
        asyncio.ensure_future(supervisor.stop_all())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    ok = await supervisor.start_all()
    if not ok:
        logger.error("Startup failed — shutting down")
        await supervisor.stop_all()
        sys.exit(1)

    if not _FRONTEND_MODE:
        print("\n  IntentFrame is running.")
        print(f"  Socket dir: {config.run_dir}")
        print(f"  Log dir:    {config.log_dir}")
        print("  Press Ctrl+C to stop.\n")

    await supervisor.monitor()


async def _cmd_status(config: SupervisorConfig) -> None:
    """Print health of each service."""
    for svc in config.services:
        socket_path = config.run_dir / svc.socket_name
        if not socket_path.exists():
            print(f"  {svc.name:<20} not running (no socket)")
            continue

        healthy = await check_health(
            socket_path=socket_path,
            health_path=svc.health_path,
            service_name=svc.name,
        )
        icon = "ok" if healthy else "UNHEALTHY"
        print(f"  {svc.name:<20} {icon:<12} {socket_path}")


async def _cmd_stop(config: SupervisorConfig) -> None:
    """Send SIGTERM to each service via its PID file / socket check."""
    print("  Stop is handled by Ctrl+C on the running supervisor.")
    print("  To stop individual services, kill their process directly.")


def backend_main() -> None:
    """Entry point for a native frontend that spawns the supervisor.

    Defaults to 'start' and enables frontend-mode JSON progress output.

    Creates a new process group so the parent can kill the entire
    tree (supervisor + all uvicorn children) with a single killpg().
    """
    os.setpgrp()
    os.environ.setdefault("INTENTFRAME_FRONTEND_MODE", "1")
    sys.argv = [sys.argv[0], "start"]
    main()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="intentframe",
        description="IntentFrame -- Multi-Process Security Framework",
    )
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("start", "Start all services"),
        ("stop", "Stop all services"),
        ("status", "Show service status"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--config",
            default=None,
            help=(
                "Path to a supervisor service-graph YAML. Falls back to the "
                "INTENTFRAME_SUPERVISOR_CONFIG env var, then the packaged "
                "supervisor/config/supervisor.yaml (no resource-registry). "
                "First-party products / tests pass "
                "intentframe_native_kit/supervisor_profile.yaml."
            ),
        )

    args = parser.parse_args()
    # Precedence: --config arg > INTENTFRAME_SUPERVISOR_CONFIG env > packaged
    # default. The env fallback lets container deployments select a profile
    # without re-plumbing the entrypoint argv (entrypoint.sh / inject_and_exec.py
    # exec `supervisor.main start` and inherit the env).
    config_path = getattr(args, "config", None) or os.environ.get(
        "INTENTFRAME_SUPERVISOR_CONFIG"
    )
    config = load_supervisor_config(config_path)

    log_stream = sys.stderr if _FRONTEND_MODE else sys.stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=log_stream,
    )

    match args.command:
        case "start":
            asyncio.run(_cmd_start(config))
        case "status":
            asyncio.run(_cmd_status(config))
        case "stop":
            asyncio.run(_cmd_stop(config))
        case _:
            parser.print_help()


if __name__ == "__main__":
    main()
