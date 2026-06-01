"""
IntentFrame Core -- FastAPI server on Unix Domain Socket.

Receives pre-built IntentFrames (from Actor SDK) and runs them through:
    Analysis Engine → Guardian → (Executor via HTTP)

No Actor on the server side.  Actor is an external SDK that agent
developers use.  This server just receives IntentFrames.

Endpoints:
    POST /handshake  -- runtime.handshake(capabilities, user_context)
    POST /process    -- runtime.process_intent(intent, user_context)
    GET  /audit      -- runtime.get_audit_log()
    GET  /health     -- health check

Startup:
    uvicorn intentframe.server:app --uds ~/.intentframe/run/intentframe.sock
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from intentframe_components.analysis import AIAnalysisEngine
from intentframe_core.types import (
    AgentCapabilities,
    ExecutionContext,
    ExecutionResult,
    IntentFrame,
    RuntimeContext,
    UserContext,
)
from intentframe_components.guardian import AIGuardian
from intentframe_components.guardian.deterministic import DeterministicGuardian
from intentframe_components.onboarding import AIOnboardingEngine
from intentframe_server.pipeline import IntentFrameRuntime

logger = logging.getLogger(__name__)

_runtime: IntentFrameRuntime | None = None


def _create_runtime() -> IntentFrameRuntime:
    """Wire up the Runtime with AI engines and an executor client.

    Executor selection is controlled by ``INTENTFRAME_EXECUTOR_MODE``:

      * ``real`` (default) — talks to the executor service over UDS via
        :class:`ExecutorHTTPClient`; normal production path.
      * ``dry_run``        — uses :class:`DryRunExecutor`, which returns
        synthetic success results without touching the host.  Intended
        for tests (root-demo in particular) that must exercise the real
        Analysis Engine + Guardian but must not run commands on the
        host.  Never enable in production.

    Unknown values raise so accidental typos never silently fall back
    to a less-safe mode.  Default is ``real``; omitting the var keeps
    existing deployments unchanged.
    """
    executor_mode = os.environ.get("INTENTFRAME_EXECUTOR_MODE", "real").strip().lower()
    verbose = os.environ.get("INTENTFRAME_VERBOSE", "1") == "1"

    if executor_mode == "real":
        from executor_client.http_client import ExecutorHTTPClient

        executor_socket = os.environ.get(
            "INTENTFRAME_EXECUTOR_SOCKET",
            "~/.intentframe/run/executor.sock",
        )
        executor = ExecutorHTTPClient(socket_path=executor_socket)
        logger.info("Executor mode: real (socket=%s)", executor_socket)
    elif executor_mode == "dry_run":
        from intentframe_server.dry_run_executor import DryRunExecutor

        executor = DryRunExecutor()
        logger.warning(
            "Executor mode: DRY_RUN — no real I/O. This runtime will NOT "
            "execute actions; intended for tests only. Never run in "
            "production with this flag set."
        )
    else:
        raise RuntimeError(
            f"Unknown INTENTFRAME_EXECUTOR_MODE: {executor_mode!r}. "
            "Expected 'real' or 'dry_run'."
        )

    executor_health = executor.health()
    execution_context = ExecutionContext(
        executor_running_as_root=executor_health.get("running_as_root", False),
        executor_uid=executor_health.get("uid", -1),
        executor_euid=executor_health.get("euid", -1),
    )
    logger.info(
        "Executor probe: uid=%d euid=%d running_as_root=%s",
        execution_context.executor_uid,
        execution_context.executor_euid,
        execution_context.executor_running_as_root,
    )

    skip_onboarding = os.environ.get("INTENTFRAME_SKIP_ONBOARDING", "0") == "1"
    onboarding = None if skip_onboarding else AIOnboardingEngine(verbose=verbose)

    return IntentFrameRuntime(
        analysis_engine=AIAnalysisEngine(verbose=verbose),
        guardian=AIGuardian(verbose=verbose),
        executor=executor,
        execution_context=execution_context,
        onboarding_engine=onboarding,
        deterministic_guardian=DeterministicGuardian(
            packages=["intentframe_native_kit.intentframe_native_bundles"],
            verbose=verbose,
        ),
        verbose=verbose,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runtime
    _runtime = _create_runtime()
    await _runtime.startup()
    logger.info("IntentFrame Core runtime ready")
    try:
        yield
    finally:
        try:
            await _runtime.aclose()
        finally:
            logger.info("IntentFrame Core runtime shut down")


app = FastAPI(
    title="IntentFrame Core",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Request / Response models ─────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "intentframe-core"


class HandshakeRequest(BaseModel):
    capabilities: AgentCapabilities
    user_context: UserContext


class ProcessRequest(BaseModel):
    intent: IntentFrame
    user_context: UserContext


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/handshake", response_model=RuntimeContext)
async def handshake(req: HandshakeRequest) -> RuntimeContext:
    assert _runtime is not None
    return await _runtime.handshake(req.capabilities, req.user_context)


@app.post("/process", response_model=ExecutionResult)
async def process(req: ProcessRequest) -> ExecutionResult:
    assert _runtime is not None
    return await _runtime.process_intent(req.intent, req.user_context)


@app.get("/audit")
async def audit() -> list[dict[str, Any]]:
    assert _runtime is not None
    return _runtime.get_audit_log()


@app.post("/audit/clear", status_code=204)
async def clear_audit() -> None:
    assert _runtime is not None
    _runtime.clear_audit_log()
