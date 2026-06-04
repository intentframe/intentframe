"""IntentFrame Gateway — top-level product orchestrator.

Single entry point for the entire IntentFrame system.  The gateway:
  1. Starts the credential vault
  2. Gates on mandatory credentials (OpenAI API key)
  3. Starts EDI email daemon early (if configured)
  4. Builds runtime env from vault and starts the supervisor
  5. Opens the platform server on macOS (via ``open`` for TCC)
  6. Bootstraps policies and workspace
  7. Starts Jarvis and optionally Telegram

Startup:
    uvicorn intentframe_gateway.server:app --uds ~/.intentframe/run/gateway.sock
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from intentframe_gateway.bootstrap import Bootstrapper
from intentframe_gateway.config import GatewayConfig, load_gateway_config
from intentframe_gateway.credential_gate import CredentialGate
from intentframe_gateway.escalation import detect_escalation_state
from intentframe_gateway.profiles import resolve_core_config_path
from intentframe_gateway.process_manager import ProcessManager
from intentframe_proxy.proxy import UDSProxy

logger = logging.getLogger(__name__)

_FRONTEND_MODE = os.environ.get("INTENTFRAME_FRONTEND_MODE") == "1"


def _emit(event: dict[str, Any]) -> None:
    """Write a JSON progress event to stdout for the frontend."""
    if _FRONTEND_MODE:
        print(json.dumps(event), flush=True)


# ── Supervisor subprocess helpers ────────────────────────────────────────────


def _supervisor_config_path() -> str:
    """Resolve the supervisor service-graph profile for first-party products.

    The gateway is a first-party product, so it defaults to the kit profile
    (kit `supervisor_profile.yaml` in the installed package) which includes the
    resource-registry. ``INTENTFRAME_SUPERVISOR_CONFIG`` overrides this for
    deployments that ship their own graph.
    """
    override = os.environ.get("INTENTFRAME_SUPERVISOR_CONFIG")
    if override:
        return override
    import intentframe_native_kit

    return str(Path(intentframe_native_kit.__file__).parent / "supervisor_profile.yaml")


async def _start_supervisor(
    config: GatewayConfig,
    runtime_env: dict[str, str],
    supervisor_config_path: str,
) -> subprocess.Popen:
    """Spawn the supervisor as a child process."""
    child_env = {**os.environ, "PYTHONUNBUFFERED": "1", **runtime_env}
    child_env["EXECUTOR_CONFIG"] = os.environ.get("EXECUTOR_CONFIG") or "jarvis_pa/executor.yaml"
    child_env["INTENTFRAME_CORE_CONFIG"] = resolve_core_config_path()

    # Detect root-demo escalation capability and stamp it into the
    # supervisor/executor env.  Both sides use this single env var as
    # the machine-level source of truth:
    #   * executor /health.running_as_root reflects it.
    #   * MacOSSandboxEngine.wrap() gates ``sudo -n`` on it.
    # Missing marker or revoked sudoers -> env="0" and every command
    # runs unprivileged, regardless of which executor YAML is loaded.
    escalation = detect_escalation_state()
    child_env["INTENTFRAME_ESCALATION_ARMED"] = "1" if escalation.armed else "0"
    if escalation.armed:
        logger.info(
            "root-demo escalation: armed (sudoers=%s, binary=%s)",
            escalation.sudoers_path,
            escalation.escalated_binary or "<unknown>",
        )
    else:
        logger.info("root-demo escalation: disarmed (%s)", escalation.reason)

    log_path = config.log_dir / "supervisor.log"
    config.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a")

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "supervisor.main", "start",
            "--config", supervisor_config_path,
        ],
        stdout=subprocess.PIPE if _FRONTEND_MODE else log_file,
        stderr=log_file,
        env=child_env,
    )
    log_file.close()
    logger.info("Supervisor spawned (pid=%d)", proc.pid)
    return proc


async def _wait_for_supervisor(
    proc: subprocess.Popen,
    config: GatewayConfig,
    supervisor_config_path: str,
    *,
    timeout: float = 120.0,
) -> bool:
    """Wait for supervisor to report all services healthy.

    In frontend mode reads JSON progress events from stdout.
    Otherwise polls sockets for health.
    """
    from supervisor.health import wait_for_health

    if _FRONTEND_MODE and proc.stdout:
        return await _read_supervisor_progress(proc, timeout)

    from supervisor.config import load_supervisor_config
    # Load the same profile the supervisor was started with so we poll the
    # exact service set it is bringing up (e.g. with/without resource-registry).
    sup_config = load_supervisor_config(supervisor_config_path)
    for svc in sup_config.services:
        sock = config.socket_path(svc.socket_name)
        _emit({"type": "starting", "service": svc.name})
        healthy = await wait_for_health(
            socket_path=sock,
            health_path=svc.health_path,
            timeout=svc.startup_timeout,
            service_name=svc.name,
        )
        if not healthy:
            logger.error("Supervisor service %s failed health check", svc.name)
            return False
        _emit({"type": "healthy", "service": svc.name})
    return True


async def _read_supervisor_progress(
    proc: subprocess.Popen,
    timeout: float,
) -> bool:
    """Read JSON progress lines from supervisor stdout until ready or failure."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    def _readline():
        return proc.stdout.readline()

    while loop.time() < deadline:
        try:
            remaining = max(0.1, deadline - loop.time())
            line = await asyncio.wait_for(
                loop.run_in_executor(None, _readline),
                timeout=remaining,
            )
        except (asyncio.TimeoutError, TimeoutError):
            break

        if not line:
            break

        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            preview = line if len(line) <= 200 else line[:200] + "..."
            logger.debug("Supervisor stdout: non-JSON line skipped: %r", preview)
            continue

        _emit(event)

        if event.get("type") == "ready":
            return True
        if event.get("type") == "failed":
            return False

    return False


def _stop_supervisor(proc: subprocess.Popen, *, timeout: float = 15.0) -> None:
    """Gracefully stop the supervisor subprocess."""
    if proc.poll() is not None:
        return
    logger.info("Stopping supervisor (pid=%d)", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Force killing supervisor")
        proc.kill()
        proc.wait()


# ── Platform server shutdown ──────────────────────────────────────────────────


async def _shutdown_platform_server(config: GatewayConfig) -> None:
    """Ask the platform server to shut down gracefully via its API."""
    import httpx

    socket_path = str(config.socket_path(config.platform_socket_name))
    try:
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://platform-server",
            timeout=5.0,
        ) as client:
            await client.post("/shutdown")
        logger.info("Platform server shutdown requested")
    except Exception as exc:
        logger.debug("Platform server shutdown skipped: %s", exc)


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_gateway_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.run_dir.mkdir(parents=True, exist_ok=True)

    pid_file = config.run_dir / "gateway.pid"
    pid_file.write_text(str(os.getpid()))

    proc_manager = ProcessManager(config)
    supervisor_proc: subprocess.Popen | None = None

    from intentframe_credentials.client import VaultClient
    vault_client = VaultClient()
    gate = CredentialGate(vault_client)

    # ── Step 1: Start credential-vault ────────────────────────────
    _emit({"type": "starting", "service": "credential-vault"})
    vault_ok = await proc_manager.start_vault()
    if not vault_ok:
        logger.error("Credential vault failed to start — aborting")
        _emit({"type": "failed", "services": ["credential-vault"]})
        app.state.partial_startup = True
        app.state.config = config
        app.state.proxies = {}
        app.state.proc_manager = proc_manager
        yield
        await proc_manager.stop_all()
        await vault_client.close()
        pid_file.unlink(missing_ok=True)
        return
    _emit({"type": "healthy", "service": "credential-vault"})

    vault_proxy = UDSProxy(
        socket_path=str(config.socket_path(config.vault_socket_name)),
        base_url="http://credential-vault",
    )

    # ── Step 2: Check mandatory credentials ───────────────────────
    if not await gate.check_mandatory():
        logger.warning("Mandatory credentials missing — partial startup")
        _emit({"type": "partial", "reason": "missing_openai_key"})
        app.state.partial_startup = True
        app.state.config = config
        app.state.proxies = {"credential-vault": vault_proxy}
        app.state.proc_manager = proc_manager
        app.state.vault_client = vault_client
        yield
        await proc_manager.stop_all()
        await vault_proxy.close()
        await vault_client.close()
        pid_file.unlink(missing_ok=True)
        return

    # ── Step 3: Start EDI early (fire-and-forget) ─────────────────
    optional = await gate.check_optional()
    if optional["edi"]:
        _emit({"type": "starting", "service": "edi"})
        await proc_manager.start_edi()
        _emit({"type": "healthy", "service": "edi"})

    # ── Step 4: Build combined env (config YAML + vault secrets) ──
    from intentframe_gateway.bootstrap import current_jarvis_identity
    from intentframe_gateway.config_loader import build_config_env
    config_env = build_config_env()
    runtime_env = await gate.build_runtime_env()
    combined_env = {**config_env, **runtime_env}
    # Must match the (user_id, agent_id) slot Bootstrapper seeded in
    # the policy registry; child processes read these via the Actor SDK.
    user_id, agent_id = current_jarvis_identity()
    combined_env["INTENTFRAME_USER_ID"] = user_id
    combined_env["INTENTFRAME_AGENT_ID"] = agent_id
    # One-release back-compat aliases.  JarvisConfig (pydantic-settings,
    # env_prefix="JARVIS_") reads JARVIS_USER_ID / JARVIS_AGENT_ID
    # directly; without these the root variant would silently default
    # agent_id to "jarvis" and the registry lookup would miss.
    combined_env["JARVIS_USER_ID"] = user_id
    combined_env["JARVIS_AGENT_ID"] = agent_id

    # ── Step 5: Start platform server (macOS only) ─────────────────
    # Must start before supervisor so the executor can reach it
    # during its own startup permission check.
    if sys.platform == "darwin":
        _emit({"type": "starting", "service": "platform-server"})
        platform_ok = await proc_manager.start_platform_server()
        if platform_ok:
            _emit({"type": "healthy", "service": "platform-server"})
        else:
            logger.warning("Platform server unavailable — native features disabled")

    # ── Step 6: Start supervisor (infra services) ─────────────────
    supervisor_config_path = _supervisor_config_path()
    supervisor_proc = await _start_supervisor(config, combined_env, supervisor_config_path)
    sup_ok = await _wait_for_supervisor(supervisor_proc, config, supervisor_config_path)
    if not sup_ok:
        logger.error("Supervisor startup failed")
        _emit({"type": "failed", "services": ["supervisor"]})
        app.state.partial_startup = True
        app.state.config = config
        app.state.proxies = {"credential-vault": vault_proxy}
        app.state.proc_manager = proc_manager
        app.state.vault_client = vault_client
        yield
        _stop_supervisor(supervisor_proc)
        await proc_manager.stop_all()
        await vault_proxy.close()
        await vault_client.close()
        pid_file.unlink(missing_ok=True)
        return

    # ── Step 7: Create proxies and bootstrap ──────────────────────
    proxies: dict[str, UDSProxy] = {"credential-vault": vault_proxy}
    for backend in config.backends:
        if backend.name == "credential-vault":
            continue
        sock = str(config.socket_path(backend.socket_name))
        proxies[backend.name] = UDSProxy(
            socket_path=sock,
            base_url=f"http://{backend.name}",
        )
    for infra in config.infra_sockets:
        sock = str(config.socket_path(infra.socket_name))
        proxies[infra.name] = UDSProxy(
            socket_path=sock,
            base_url=f"http://{infra.name}",
        )

    bootstrapper = Bootstrapper()
    await bootstrapper.reconcile(config, proxies)

    # ── Step 8: Start Jarvis ──────────────────────────────────────
    _emit({"type": "starting", "service": "jarvis"})
    jarvis_ok = await proc_manager.start_jarvis(env=combined_env)
    if not jarvis_ok:
        logger.error("Jarvis failed to start")
        _emit({"type": "failed", "services": ["jarvis"]})
    else:
        _emit({"type": "healthy", "service": "jarvis"})

    # ── Step 9: Start Telegram (if credentials exist) ─────────────
    if optional["telegram"] and jarvis_ok:
        _emit({"type": "starting", "service": "telegram"})
        await proc_manager.start_telegram(env=combined_env)

    # ── Step 10: Open store and event stream ──────────────────────
    from intentframe_gateway.store import AppStore
    store = AppStore(config.db_path)
    await store.open()

    from intentframe_gateway.events import UnifiedEventStream
    event_stream = UnifiedEventStream(config, proxies)
    await event_stream.start()

    app.state.partial_startup = False
    app.state.config = config
    app.state.proxies = proxies
    app.state.store = store
    app.state.event_stream = event_stream
    app.state.proc_manager = proc_manager
    app.state.vault_client = vault_client

    _emit({
        "type": "ready",
        "run_dir": str(config.run_dir),
        "log_dir": str(config.log_dir),
    })
    logger.info("Gateway ready — system fully started")

    yield

    # ── Shutdown ──────────────────────────────────────────────────
    logger.info("Gateway shutting down...")

    # Stop the platform server first (independent app, needs explicit call)
    if sys.platform == "darwin":
        await _shutdown_platform_server(config)

    await proc_manager.stop_all()
    await event_stream.stop()
    await store.close()
    if supervisor_proc:
        _stop_supervisor(supervisor_proc)
    for proxy in proxies.values():
        await proxy.close()
    await vault_client.close()
    pid_file.unlink(missing_ok=True)
    logger.info("Gateway shut down")


# ── App ──────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="IntentFrame Gateway",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


# --- Register route modules ---

from intentframe_gateway.routes.jarvis import router as jarvis_router  # noqa: E402
from intentframe_gateway.routes.policies import router as policies_router  # noqa: E402
from intentframe_gateway.routes.vault import router as vault_router  # noqa: E402
from intentframe_gateway.routes.system import router as system_router  # noqa: E402
from intentframe_gateway.routes.config_routes import router as config_router  # noqa: E402
from intentframe_gateway.routes.events_routes import router as events_router  # noqa: E402
from intentframe_gateway.routes.edi import router as edi_router  # noqa: E402
from intentframe_gateway.routes.platform import router as platform_router  # noqa: E402
from intentframe_gateway.routes.audit import router as audit_router  # noqa: E402

app.include_router(jarvis_router)
app.include_router(policies_router)
app.include_router(vault_router)
app.include_router(system_router)
app.include_router(config_router)
app.include_router(events_router)
app.include_router(edi_router)
app.include_router(platform_router)
app.include_router(audit_router)
