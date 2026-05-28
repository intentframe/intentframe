"""
Executor -- FastAPI server on Unix Domain Socket.

Wraps the ExecutorGateway with HTTP endpoints, consistent with
the other IntentFrame services. Replaces the raw length-prefixed
Unix socket transport with standard HTTP.

Endpoints:
    POST /execute   -- gateway.handle(request)
    POST /rollback  -- gateway.handle_rollback(rollback_id)
    GET  /health    -- health check

Startup:
    uvicorn executor.server:app --uds ~/.intentframe/run/executor.sock
"""

from __future__ import annotations

import logging
import os
import platform as _platform
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from executor.config import load_config
from executor_sdk.exceptions import ConfigurationError
from executor.main import build_gateway
from executor_sdk.models import (
    ExecutionRequest,
    ExecutionResult,
)

logger = logging.getLogger(__name__)

_gateway = None
_worker_pool = None

_PLATFORM_REGISTRY = {
    "macos": "intentframe_executor_pack_macos",
    "darwin": "intentframe_executor_pack_macos",
}


def _register_platform(platform_name: str) -> None:
    """Register platform-specific implementations from config.

    Args:
        platform_name: 'macos', 'linux', or 'auto' (detect from OS).
    """
    if platform_name == "auto":
        platform_name = _platform.system().lower()

    module_path = _PLATFORM_REGISTRY.get(platform_name)
    if module_path is None:
        raise ConfigurationError(
            f"Unsupported platform: '{platform_name}'. "
            f"Available: {', '.join(sorted(_PLATFORM_REGISTRY))}",
        )

    import importlib
    mod = importlib.import_module(module_path)
    mod.register_all()
    logger.info("Platform registered: %s", platform_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _gateway, _worker_pool
    config = load_config(config_path=os.environ.get("EXECUTOR_CONFIG"))
    _register_platform(config.platform)

    if sys.platform == "darwin":
        try:
            from intentframe_executor_pack_macos.permissions import check_permissions
            check_permissions(config.adapters.enabled)
        except Exception as exc:
            logger.warning("Platform server permission check failed: %s", exc)

    _gateway, _transport, _worker_pool = build_gateway(config)
    logger.info("Executor gateway ready")
    yield
    if _worker_pool:
        await _worker_pool.shutdown()
    if _gateway:
        _gateway.close()
    logger.info("Executor gateway shut down")


app = FastAPI(
    title="IntentFrame Executor",
    version="0.1.0",
    lifespan=lifespan,
)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "executor"
    uid: int = 0
    euid: int = 0
    running_as_root: bool = False
    pid: int = 0


class RollbackRequest(BaseModel):
    rollback_id: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    euid = os.geteuid()
    # ``running_as_root`` reflects machine-level root capability for
    # RUN_COMMAND, not the executor process's own privilege.  Two paths
    # to ``True``:
    #   1. The executor actually runs as UID 0 (rare -- only if the
    #      whole stack was launched with sudo).
    #   2. The gateway advertised ``INTENTFRAME_ESCALATION_ARMED=1`` in
    #      our env at spawn time, meaning ``/etc/sudoers.d/intentframe-run``
    #      is installed and the sandbox engine is allowed to wrap
    #      sandbox-exec with ``sudo -n``.
    # No runtime probe, no YAML coupling -- the YAML only decides
    # whether each individual command opts into the escalation.
    env_armed = os.environ.get("INTENTFRAME_ESCALATION_ARMED") == "1"
    return HealthResponse(
        uid=os.getuid(),
        euid=euid,
        running_as_root=(euid == 0) or env_armed,
        pid=os.getpid(),
    )

@app.post("/execute", response_model=ExecutionResult)
async def execute(request: ExecutionRequest) -> ExecutionResult:
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    return await _gateway.handle(request)


@app.post("/rollback", response_model=ExecutionResult)
async def rollback(req: RollbackRequest) -> ExecutionResult:
    if _gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    return await _gateway.handle_rollback(req.rollback_id)
