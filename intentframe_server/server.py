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
    ExecutionResult,
    IntentFrame,
    RuntimeContext,
    UserContext,
)
from intentframe_components.guardian import AIGuardian
from intentframe_components.onboarding import AIOnboardingEngine
from intentframe_server.pipeline import IntentFrameRuntime

logger = logging.getLogger(__name__)

_runtime: IntentFrameRuntime | None = None


def _create_runtime() -> IntentFrameRuntime:
    """Wire up the Runtime with AI engines and HTTP executor client."""
    from executor_client.http_client import ExecutorHTTPClient

    executor_socket = os.environ.get(
        "INTENTFRAME_EXECUTOR_SOCKET",
        "~/.intentframe/run/executor.sock",
    )
    verbose = os.environ.get("INTENTFRAME_VERBOSE", "1") == "1"

    executor = ExecutorHTTPClient(socket_path=executor_socket)

    skip_onboarding = os.environ.get("INTENTFRAME_SKIP_ONBOARDING", "0") == "1"
    onboarding = None if skip_onboarding else AIOnboardingEngine(verbose=verbose)

    return IntentFrameRuntime(
        analysis_engine=AIAnalysisEngine(verbose=verbose),
        guardian=AIGuardian(verbose=verbose),
        executor=executor,
        onboarding_engine=onboarding,
        verbose=verbose,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runtime
    _runtime = _create_runtime()
    logger.info("IntentFrame Core runtime ready")
    yield
    from intentframe_server.enrichers.email import close as close_email_enricher
    await close_email_enricher()
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
