"""Tests for ValidationResult.decision_path plumbing.

The pipeline used to detect fast-path decisions via a brittle string
check on ``validation.message`` (``"fast-path" in message.lower()``).
That coupled audit semantics to a log string format.  We now carry the
decision path explicitly on ``ValidationResult.decision_path`` and the
pipeline reads it for audit + metrics.

These tests pin the new contract:

  - Guardian sets ``decision_path="fast_path"`` on the deterministic
    ALLOW short-circuit.
  - Guardian sets ``decision_path="ai_path"`` on every other internal
    path (permission/constraint/domain BLOCK, AI-rendered judgment).
  - The pipeline surfaces ``decision_path`` verbatim into the audit
    log (authoritative), only falling back to the legacy substring
    check when a guardian predates the field (set to empty).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from intentframe_native_kit.action_registry.types import ActionType
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


def _run(coro):
    return asyncio.run(coro)


def _user_context() -> UserContext:
    # safe=False so DeterministicGuardian falls through to UNDECIDED
    # and the pipeline actually invokes the (mocked) AIGuardian whose
    # ValidationResult these tests pin.
    return UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": ActionPermission(safe=False)},
    )


def _intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x.txt",
        reason="test",
        agent_id="test_agent",
    )


def _safe_analysis() -> AnalysisReport:
    return AnalysisReport(
        stated_intent="read",
        risk_factors={"overall": RiskLevel.LOW},
        reversibility=Reversibility.FULLY_REVERSIBLE,
        confidence=1.0,
        recommendation="ok",
    )


def _make_runtime(validation: ValidationResult) -> IntentFrameRuntime:
    analysis_engine = AsyncMock()
    analysis_engine.analyze = AsyncMock(return_value=_safe_analysis())

    guardian = AsyncMock()
    guardian.validate = AsyncMock(return_value=validation)

    executor = MagicMock()
    executor.execute = MagicMock(
        return_value=ExecutionResult(success=True, data={"stdout": "ok"})
    )

    runtime = IntentFrameRuntime(
        analysis_engine=analysis_engine,
        guardian=guardian,
        executor=executor,
        verbose=False,
    )
    runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)
    return runtime


class TestValidationResultField:
    def test_default_is_ai_path(self):
        intent = _intent()
        r = ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            message="",
        )
        assert r.decision_path == "ai_path"

    def test_accepts_fast_path(self):
        r = ValidationResult(
            decision=Decision.ALLOW,
            intent=_intent(),
            decision_path="fast_path",
        )
        assert r.decision_path == "fast_path"

    def test_accepts_deterministic(self):
        r = ValidationResult(
            decision=Decision.ALLOW,
            intent=_intent(),
            decision_path="deterministic",
        )
        assert r.decision_path == "deterministic"

    def test_rejects_unknown_value(self):
        with pytest.raises(Exception):
            ValidationResult(
                decision=Decision.ALLOW,
                intent=_intent(),
                decision_path="mystery",
            )


class TestPipelineReadsDecisionPath:
    def test_fast_path_decision_in_audit(self):
        validation = ValidationResult(
            decision=Decision.ALLOW,
            intent=_intent(),
            message="Permitted (fast-path): READ_FILE",
            decision_path="fast_path",
        )
        runtime = _make_runtime(validation)
        _run(runtime.process_intent(_intent(), _user_context()))

        assert runtime.audit_log[0]["decision_path"] == "fast_path"

    def test_ai_path_decision_in_audit(self):
        validation = ValidationResult(
            decision=Decision.ALLOW,
            intent=_intent(),
            message="AI allowed",
            decision_path="ai_path",
        )
        runtime = _make_runtime(validation)
        _run(runtime.process_intent(_intent(), _user_context()))

        assert runtime.audit_log[0]["decision_path"] == "ai_path"

    def test_deterministic_decision_in_audit(self):
        """Reserved value is preserved end-to-end — required by
        DeterministicGuardian which emits ``decision_path="deterministic"``."""
        validation = ValidationResult(
            decision=Decision.ALLOW,
            intent=_intent(),
            message="deterministic allow",
            decision_path="deterministic",
        )
        runtime = _make_runtime(validation)
        _run(runtime.process_intent(_intent(), _user_context()))

        assert runtime.audit_log[0]["decision_path"] == "deterministic"

    def test_misleading_message_does_not_override_field(self):
        """Prior bug: a BLOCK message containing 'fast-path' in English
        (e.g. 'not eligible for fast-path') would get audited as
        fast_path.  Now decision_path is authoritative."""
        validation = ValidationResult(
            decision=Decision.BLOCK,
            intent=_intent(),
            message="This intent is not eligible for fast-path review.",
            decision_path="ai_path",
        )
        runtime = _make_runtime(validation)
        _run(runtime.process_intent(_intent(), _user_context()))

        assert runtime.audit_log[0]["decision_path"] == "ai_path"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
