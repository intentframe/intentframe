"""System routes — /system/*

Health, service status, log access, lifecycle management, and
graceful shutdown for the entire IntentFrame system.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from intentframe_gateway.escalation import detect_escalation_state

router = APIRouter(prefix="/system", tags=["system"])

logger = logging.getLogger(__name__)

_MANAGED_SERVICES = frozenset({"jarvis", "edi", "telegram"})


async def _build_combined_env(request: Request) -> dict[str, str]:
    """Build the merged config-YAML + vault-secrets env dict for child processes."""
    from intentframe_gateway.config_loader import build_config_env
    config_env = build_config_env()
    vault_client = getattr(request.app.state, "vault_client", None)
    if vault_client:
        from intentframe_gateway.credential_gate import CredentialGate
        gate = CredentialGate(vault_client)
        runtime_env = await gate.build_runtime_env()
    else:
        runtime_env = {}
    return {**config_env, **runtime_env}


# ── Credential status ─────────────────────────────────────────────────────────


@router.get("/credential-status")
async def credential_status(request: Request):
    """Check all credential/config categories and return structured status.

    Returns a list of credential items, each with:
      name, key, required, configured, hint (CLI command), help (human guidance).
    """
    vault_client = getattr(request.app.state, "vault_client", None)
    if not vault_client:
        raise HTTPException(503, "Vault not available")

    from intentframe_gateway.credential_gate import CredentialGate
    from intentframe_gateway.config_loader import read_config_yaml

    gate = CredentialGate(vault_client)
    yaml_config = read_config_yaml()

    has_openai = await vault_client.has("openai", "api_key")
    has_telegram_token = await vault_client.has("telegram", "bot_token")

    telegram_cfg = yaml_config.get("telegram") or {}
    has_telegram_user_id = bool(telegram_cfg.get("allowed_user_id"))

    has_edi = await gate._has_email_accounts()

    return {
        "credentials": [
            {
                "name": "LLM API Key",
                "key": "openai/api_key",
                "required": True,
                "configured": has_openai,
                "hint": "vault set openai api_key",
                "help": "https://platform.openai.com/api-keys",
            },
            {
                "name": "Telegram Bot Token",
                "key": "telegram/bot_token",
                "required": False,
                "configured": has_telegram_token,
                "hint": "vault set telegram bot_token",
                "help": "Create a bot via @BotFather on Telegram",
            },
            {
                "name": "Telegram User ID",
                "key": "telegram.allowed_user_id",
                "required": False,
                "configured": has_telegram_user_id,
                "hint": "env set telegram.allowed_user_id YOUR_ID",
                "help": "Send /start to @userinfobot on Telegram",
            },
            {
                "name": "Email Account",
                "key": "email.*/password",
                "required": False,
                "configured": has_edi,
                "hint": "vault set email.YOU@GMAIL.COM password\n"
                        "         then:  edi add YOU@GMAIL.COM",
                "help": "Use an App Password (Gmail/Outlook/iCloud)",
            },
        ],
    }


# ── Health & status ──────────────────────────────────────────────────────────


@router.get("/health")
async def aggregated_health(request: Request):
    """Poll /health on all known backend sockets in parallel."""
    config = request.app.state.config
    proxies = request.app.state.proxies

    async def check_one(name: str):
        proxy = proxies.get(name)
        if not proxy:
            return name, False, None
        try:
            healthy = await proxy.health("/health")
            return name, healthy, None
        except Exception as exc:
            logger.warning("Health probe raised for %s: %s", name, exc)
            return name, False, str(exc)

    all_backends = list(config.backends) + list(config.infra_sockets)
    tasks = [check_one(b.name) for b in all_backends]
    results = await asyncio.gather(*tasks)

    services = {}
    all_healthy = True
    for name, healthy, error in results:
        services[name] = {"healthy": healthy}
        if error:
            services[name]["error"] = error
        if not healthy:
            all_healthy = False

    proc_manager = getattr(request.app.state, "proc_manager", None)
    if proc_manager:
        for status in proc_manager.all_status().values():
            name = status["name"]
            if name in services:
                continue
            services[name] = {
                "healthy": status.get("healthy", False),
                "running": status.get("running", False),
                "pid": status.get("pid"),
            }

    unhealthy = [n for n, meta in services.items() if not meta.get("healthy", False)]
    if unhealthy:
        logger.debug("Aggregated /system/health: degraded: %s", ", ".join(unhealthy))

    # Root-demo + profile block for CLI surfacing.  Computed on every
    # call because the installer/uninstaller can run while the gateway
    # is up; the marker/sudoers state is cheap to re-stat.
    escalation = detect_escalation_state()
    profile = os.environ.get("INTENTFRAME_PROFILE", "user")
    executor_running_as_root = (os.geteuid() == 0) or escalation.armed
    root_demo = {
        "profile": profile,
        **escalation.as_health_payload(),
        "executor_running_as_root": executor_running_as_root,
    }

    return {
        "status": "healthy" if all_healthy else "degraded",
        "partial_startup": getattr(request.app.state, "partial_startup", False),
        "services": services,
        "root_demo": root_demo,
    }


@router.get("/services")
async def service_status(request: Request):
    """Per-service detail: name, socket path, PID, healthy."""
    config = request.app.state.config
    proxies = request.app.state.proxies

    async def check_one(backend):
        sock_path = config.socket_path(backend.socket_name)
        proxy = proxies.get(backend.name)
        pid = _read_pid(config.run_dir, backend.name)
        socket_exists = sock_path.exists()

        healthy = False
        if proxy and socket_exists:
            healthy = await proxy.health(backend.health_path)

        return {
            "name": backend.name,
            "socket": str(sock_path),
            "socket_exists": socket_exists,
            "pid": pid,
            "healthy": healthy,
        }

    all_backends = list(config.backends) + list(config.infra_sockets)
    services = await asyncio.gather(*[check_one(b) for b in all_backends])
    result = list(services)
    seen = {b.name for b in all_backends}

    proc_manager = getattr(request.app.state, "proc_manager", None)
    if proc_manager:
        for name in ("credential-vault", "jarvis", "edi", "telegram"):
            if name in seen:
                continue
            status = proc_manager.status(name)
            if status.get("pid"):
                result.append(status)

    return {"services": result}


# ── Lifecycle ────────────────────────────────────────────────────────────────


@router.post("/{service}/start")
async def start_service(request: Request, service: str):
    """Start a managed process (jarvis, edi, telegram)."""
    if service not in _MANAGED_SERVICES:
        raise HTTPException(404, f"Unknown managed service: {service}")

    proc_manager = request.app.state.proc_manager

    if service == "jarvis":
        env = await _build_combined_env(request)
        ok = await proc_manager.start_jarvis(env=env)
    elif service == "edi":
        ok = await proc_manager.start_edi()
    elif service == "telegram":
        env = await _build_combined_env(request)
        ok = await proc_manager.start_telegram(env=env)
    else:
        ok = False

    if not ok:
        raise HTTPException(500, f"Failed to start {service}")
    return {"service": service, "status": "started"}


@router.post("/{service}/stop")
async def stop_service(request: Request, service: str):
    """Stop a managed process."""
    if service not in _MANAGED_SERVICES:
        raise HTTPException(404, f"Unknown managed service: {service}")
    proc_manager = request.app.state.proc_manager
    await proc_manager.stop(service)
    return {"service": service, "status": "stopped"}


@router.post("/{service}/restart")
async def restart_service(request: Request, service: str):
    """Restart a managed process (stop then start)."""
    if service not in _MANAGED_SERVICES:
        raise HTTPException(404, f"Unknown managed service: {service}")
    proc_manager = request.app.state.proc_manager
    await proc_manager.stop(service)
    return await start_service(request, service)


@router.get("/{service}/status")
async def managed_service_status(request: Request, service: str):
    """Get status of a managed process."""
    proc_manager = getattr(request.app.state, "proc_manager", None)
    if not proc_manager:
        raise HTTPException(503, "Process manager not available")
    return proc_manager.status(service)


@router.post("/bootstrap")
async def run_bootstrap(request: Request):
    """Re-run the bootstrap/reconcile step (seed policies + workspace)."""
    config = request.app.state.config
    proxies = request.app.state.proxies
    from intentframe_gateway.bootstrap import Bootstrapper
    bootstrapper = Bootstrapper()
    await bootstrapper.reconcile(config, proxies)
    return {"status": "reconciled"}


@router.post("/retry-startup")
async def retry_startup(request: Request):
    """Retry the full startup sequence after credentials are stored.

    Only meaningful when the gateway is in partial startup mode
    (missing mandatory credentials). Returns 400 if already fully started.
    """
    if not getattr(request.app.state, "partial_startup", False):
        raise HTTPException(400, "System is already fully started")
    return {
        "status": "restart_required",
        "message": "Restart the gateway process to complete startup with new credentials.",
    }


# ── Shutdown ─────────────────────────────────────────────────────────────────


@router.post("/shutdown")
async def shutdown(request: Request):
    """Gracefully shut down the entire IntentFrame system.

    Sends SIGTERM to the gateway process, which triggers the lifespan
    teardown (stops platform server, managed processes, supervisor,
    closes proxies, removes PID file).  Returns immediately — the
    caller should poll the process or PID file to confirm exit.
    """
    logger.info("Shutdown requested via API")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting_down"}


# ── Logs ─────────────────────────────────────────────────────────────────────


@router.get("/logs/{service}")
async def log_tail(request: Request, service: str, lines: int = 100):
    """Read last N lines from a service's log file."""
    config = request.app.state.config
    log_path = config.log_dir / f"{service}.log"

    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"No log file for {service}")

    tail = _tail_file(log_path, lines)
    return {"service": service, "lines": tail, "path": str(log_path)}


@router.get("/logs/{service}/stream")
async def log_stream(request: Request, service: str):
    """SSE tail of a service's log file."""
    config = request.app.state.config
    log_path = config.log_dir / f"{service}.log"

    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"No log file for {service}")

    async def tail_generator():
        with open(log_path) as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if line:
                    yield {
                        "event": "log",
                        "data": json.dumps({"service": service, "line": line.rstrip()}),
                    }
                else:
                    await asyncio.sleep(0.5)

    return EventSourceResponse(tail_generator())


# ── System config (non-sensitive env YAML) ───────────────────────────────────


@router.get("/config-env")
async def get_config_env():
    """Return the parsed system config YAML and its resolved env vars."""
    from intentframe_gateway.config_loader import build_config_env, read_config_yaml
    return {
        "config": read_config_yaml(),
        "resolved_env": build_config_env(),
    }


class _ConfigEnvSetBody(BaseModel):
    key: str
    value: str


@router.put("/config-env")
async def set_config_env(body: _ConfigEnvSetBody):
    """Set a value in the system config YAML by dotted key (e.g. ``identity.user_id``)."""
    from intentframe_gateway.config_loader import read_config_yaml, set_config_value, build_config_env
    set_config_value(body.key, body.value)
    return {
        "key": body.key,
        "value": body.value,
        "config": read_config_yaml(),
        "resolved_env": build_config_env(),
    }


@router.delete("/config-env/{key:path}")
async def delete_config_env(key: str):
    """Delete a value from the system config YAML by dotted key."""
    from intentframe_gateway.config_loader import delete_config_value
    deleted = delete_config_value(key)
    if not deleted:
        raise HTTPException(404, f"Config key not found: {key}")
    return {"key": key, "deleted": True}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_pid(run_dir: Path, service_name: str) -> int | None:
    pid_file = run_dir / f"{service_name}.pid"
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except (ValueError, OSError) as exc:
            logger.debug("Could not read PID file %s: %s", pid_file, exc)
    return None


def _tail_file(path: Path, n: int) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return []
            chunk_size = min(size, n * 200)
            f.seek(max(0, size - chunk_size))
            data = f.read().decode("utf-8", errors="replace")
            lines = data.splitlines()
            return lines[-n:]
    except OSError as exc:
        logger.debug("Could not tail log file %s: %s", path, exc)
        return []
