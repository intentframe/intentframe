"""Concurrency tripwires for the runtime security lane lock."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from action_registry.types import ActionType
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicResult,
)
from intentframe_core.enums import Decision, Reversibility, RiskLevel
from intentframe_core.types import (
    AnalysisReport,
    ExecutionResult,
    IntentFrame,
    UserContext,
    ValidationResult,
)
from intentframe_server.pipeline import IntentFrameRuntime
from policy_registry.models import ActionPermission


class _Tripwire:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_seen = 0

    @contextmanager
    def enter(self, stage: str):
        self.in_flight += 1
        self.max_seen = max(self.max_seen, self.in_flight)
        try:
            assert self.in_flight == 1, f"Concurrent runtime stage detected: {stage}"
            yield
        finally:
            self.in_flight -= 1


def _analysis() -> AnalysisReport:
    return AnalysisReport(
        stated_intent="read file",
        risk_factors={"overall": RiskLevel.LOW},
        reversibility=Reversibility.FULLY_REVERSIBLE,
        confidence=1.0,
        recommendation="allow",
    )


class _YieldingAnalysis:
    def __init__(self, tripwire: _Tripwire) -> None:
        self.tripwire = tripwire

    async def analyze(self, intent, **_kwargs) -> AnalysisReport:
        with self.tripwire.enter("analysis"):
            await asyncio.sleep(0)
            return _analysis()


class _YieldingGuardian:
    def __init__(self, tripwire: _Tripwire) -> None:
        self.tripwire = tripwire

    async def validate(self, intent, analysis, user_context, **_kwargs):
        with self.tripwire.enter("guardian"):
            await asyncio.sleep(0)
            return ValidationResult(
                decision=Decision.ALLOW,
                intent=intent,
                analysis=analysis,
                message="allowed",
                decision_path="ai_path",
            )


class _CompletedExecutor:
    def execute(self, validated_intent: IntentFrame) -> ExecutionResult:
        return ExecutionResult(success=True, data={"action": validated_intent.action})


class _AwaitableResult:
    def __await__(self):
        async def _result():
            return ExecutionResult(success=True)

        return _result().__await__()


class _PrematureExecutor:
    def execute(self, validated_intent: IntentFrame) -> _AwaitableResult:
        return _AwaitableResult()


def _user_context() -> UserContext:
    return UserContext(
        user_id="test",
        allowed_actions={"READ_HOST_FILE": ActionPermission(safe=False)},
    )


def _intent(index: int) -> IntentFrame:
    return IntentFrame(
        action=ActionType.READ_HOST_FILE,
        target=f"invoice-{index}.pdf",
        reason="concurrency test",
        agent_id="test_agent",
        sequence_id=index,
    )


def _runtime(executor=None) -> tuple[IntentFrameRuntime, _Tripwire]:
    tripwire = _Tripwire()
    det_guardian = MagicMock()
    det_guardian.decide_async = AsyncMock(
        return_value=DeterministicResult(
            decision=DeterministicDecision.UNDECIDED,
            matched_gate="undecided",
        ),
    )
    runtime = IntentFrameRuntime(
        analysis_engine=_YieldingAnalysis(tripwire),
        guardian=_YieldingGuardian(tripwire),
        executor=executor or _CompletedExecutor(),
        deterministic_guardian=det_guardian,
        verbose=False,
    )
    runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)
    return runtime, tripwire


@pytest.mark.asyncio
async def test_process_intent_serializes_parallel_requests(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTENTFRAME_LOG_DIR", str(tmp_path))
    runtime, tripwire = _runtime()
    user_context = _user_context()

    results = await asyncio.gather(
        *(runtime.process_intent(_intent(i), user_context) for i in range(5))
    )

    assert all(result.success for result in results)
    assert tripwire.max_seen == 1
    assert len(runtime.audit_log) == 5


@pytest.mark.asyncio
async def test_executor_must_return_completed_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTENTFRAME_LOG_DIR", str(tmp_path))
    runtime, _tripwire = _runtime(executor=_PrematureExecutor())

    with pytest.raises(TypeError, match="requires a completed ExecutionResult"):
        await runtime.process_intent(_intent(1), _user_context())
