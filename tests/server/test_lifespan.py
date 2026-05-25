"""FastAPI lifespan delegates bundle shutdown to the runtime."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from intentframe_server.dry_run_executor import DryRunExecutor
from intentframe_server.pipeline import IntentFrameRuntime
from intentframe_server.server import lifespan
from tests.test_runtime_lifecycle import _AllowAnalysis, _AllowGuardian


@pytest.mark.asyncio
async def test_lifespan_calls_runtime_startup_and_aclose() -> None:
    runtime = MagicMock()
    runtime.startup = AsyncMock()
    runtime.aclose = AsyncMock()

    with patch("intentframe_server.server._create_runtime", return_value=runtime):
        app = FastAPI()
        async with lifespan(app):
            runtime.startup.assert_awaited_once()
            runtime.aclose.assert_not_awaited()

    runtime.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_aclose_runs_after_body_exception() -> None:
    runtime = MagicMock()
    runtime.startup = AsyncMock()
    runtime.aclose = AsyncMock()

    with patch("intentframe_server.server._create_runtime", return_value=runtime):
        app = FastAPI()
        with pytest.raises(RuntimeError, match="request failed"):
            async with lifespan(app):
                raise RuntimeError("request failed")

    runtime.startup.assert_awaited_once()
    runtime.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_runs_real_runtime_cleanup_on_exception() -> None:
    runtime = IntentFrameRuntime(
        analysis_engine=_AllowAnalysis(),
        guardian=_AllowGuardian(),
        executor=DryRunExecutor(),
        verbose=False,
    )

    with patch("intentframe_server.server._create_runtime", return_value=runtime):
        with patch(
            "intentframe_bundle_sdk.lifecycle.shutdown_bundles",
            new=AsyncMock(),
        ) as mock_shutdown:
            app = FastAPI()
            with pytest.raises(RuntimeError, match="boom"):
                async with lifespan(app):
                    raise RuntimeError("boom")

            mock_shutdown.assert_awaited_once()
