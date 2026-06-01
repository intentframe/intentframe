"""TOCTOU regression test for the invoice delete/read race in the docs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from intentframe_native_kit.action_registry.types import ActionType
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


@dataclass
class _World:
    files: dict[str, str] = field(default_factory=lambda: {"invoice.pdf": "paid"})
    snapshots: dict[int, bool] = field(default_factory=dict)
    events: list[tuple[int, str, bool]] = field(default_factory=list)


class _InvoiceAnalysis:
    async def analyze(self, intent, **_kwargs) -> AnalysisReport:
        await asyncio.sleep(0)
        return AnalysisReport(
            stated_intent=f"{intent.action} invoice.pdf",
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation="allow",
        )


class _SnapshotGuardian:
    def __init__(self, world: _World) -> None:
        self.world = world

    async def validate(self, intent, analysis, user_context, **_kwargs):
        exists = "invoice.pdf" in self.world.files
        self.world.snapshots[intent.sequence_id] = exists
        self.world.events.append((intent.sequence_id, "check", exists))
        await asyncio.sleep(0)
        return ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            analysis=analysis,
            message="allowed",
            decision_path="ai_path",
        )


class _InvoiceExecutor:
    def __init__(self, world: _World) -> None:
        self.world = world

    def execute(self, validated_intent: IntentFrame) -> ExecutionResult:
        checked_exists = self.world.snapshots[validated_intent.sequence_id]
        current_exists = "invoice.pdf" in self.world.files
        self.world.events.append(
            (validated_intent.sequence_id, "use", current_exists)
        )

        if checked_exists != current_exists:
            return ExecutionResult(
                success=False,
                error="TOCTOU: invoice state changed between check and use",
                data={"checked_exists": checked_exists, "current_exists": current_exists},
            )

        if validated_intent.action is ActionType.DELETE_HOST_FILE:
            self.world.files.pop("invoice.pdf", None)

        return ExecutionResult(
            success=True,
            data={"exists_at_check": checked_exists, "exists_at_use": current_exists},
        )


def _user_context() -> UserContext:
    return UserContext(
        user_id="test",
        allowed_actions={
            "DELETE_HOST_FILE": ActionPermission(safe=False),
            "READ_HOST_FILE": ActionPermission(safe=False),
        },
    )


def _intent(action: ActionType, sequence_id: int) -> IntentFrame:
    return IntentFrame(
        action=action,
        target="invoice.pdf",
        reason="doc TOCTOU scenario",
        agent_id="test_agent",
        sequence_id=sequence_id,
    )


def _runtime(world: _World) -> IntentFrameRuntime:
    det_guardian = MagicMock()
    det_guardian.decide_async = AsyncMock(
        return_value=DeterministicResult(
            decision=DeterministicDecision.UNDECIDED,
            matched_gate="undecided",
        ),
    )
    runtime = IntentFrameRuntime(
        analysis_engine=_InvoiceAnalysis(),
        guardian=_SnapshotGuardian(world),
        executor=_InvoiceExecutor(world),
        deterministic_guardian=det_guardian,
        verbose=False,
    )
    runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)
    return runtime


@pytest.mark.asyncio
async def test_invoice_delete_and_read_are_strictly_serialized(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTENTFRAME_LOG_DIR", str(tmp_path))
    world = _World()
    runtime = _runtime(world)
    user_context = _user_context()

    delete = _intent(ActionType.DELETE_HOST_FILE, sequence_id=1)
    read = _intent(ActionType.READ_HOST_FILE, sequence_id=2)

    results = await asyncio.gather(
        runtime.process_intent(delete, user_context),
        runtime.process_intent(read, user_context),
    )

    assert all(result.success for result in results)
    assert len(runtime.audit_log) == 2

    event_sequences = [sequence_id for sequence_id, _stage, _exists in world.events]
    assert event_sequences in ([1, 1, 2, 2], [2, 2, 1, 1])

    for sequence_id, checked_exists in world.snapshots.items():
        use_events = [
            exists
            for event_sequence_id, stage, exists in world.events
            if event_sequence_id == sequence_id and stage == "use"
        ]
        assert use_events == [checked_exists]
