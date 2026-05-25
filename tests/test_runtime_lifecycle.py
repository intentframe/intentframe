"""Runtime startup/shutdown delegates to bundle lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intentframe_server.dry_run_executor import DryRunExecutor
from intentframe_server.pipeline import IntentFrameRuntime


class _AllowGuardian:
    async def validate(self, intent, analysis, user_context, **kwargs):
        from intentframe_core.enums import Decision
        from intentframe_core.types import ValidationResult

        return ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            analysis=analysis,
            message="ok",
        )


class _AllowAnalysis:
    async def analyze(self, intent, **kwargs):
        from intentframe_core.enums import Reversibility, RiskLevel
        from intentframe_core.types import AnalysisReport

        return AnalysisReport(
            stated_intent="test",
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation="allow",
        )


@pytest.mark.asyncio
async def test_runtime_startup_invokes_startup_bundles() -> None:
    runtime = IntentFrameRuntime(
        analysis_engine=_AllowAnalysis(),
        guardian=_AllowGuardian(),
        executor=DryRunExecutor(),
        verbose=False,
    )

    with patch(
        "intentframe_bundle_sdk.lifecycle.startup_bundles",
        new=AsyncMock(),
    ) as mock_startup:
        await runtime.startup()
        mock_startup.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_aclose_invokes_shutdown_bundles_and_executor_close() -> None:
    runtime = IntentFrameRuntime(
        analysis_engine=_AllowAnalysis(),
        guardian=_AllowGuardian(),
        executor=DryRunExecutor(),
        verbose=False,
    )

    with patch(
        "intentframe_bundle_sdk.lifecycle.shutdown_bundles",
        new=AsyncMock(),
    ) as mock_shutdown:
        await runtime.aclose()
        mock_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_aclose_awaits_async_executor_close() -> None:
    class AsyncClosingExecutor(DryRunExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    executor = AsyncClosingExecutor()
    runtime = IntentFrameRuntime(
        analysis_engine=_AllowAnalysis(),
        guardian=_AllowGuardian(),
        executor=executor,
        verbose=False,
    )

    with patch(
        "intentframe_bundle_sdk.lifecycle.shutdown_bundles",
        new=AsyncMock(),
    ):
        await runtime.aclose()

    assert executor.closed is True
