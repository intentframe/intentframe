"""Regression: ``ae_prompt_id`` / ``guardian_prompt_id`` must never leak
across requests.

Bundle C added observability fields on the AE and Guardian engines
(``last_prompt_id``) that the pipeline copies into the audit entry.
The engines only assign these attributes inside their own ``analyze()``
/ ``validate()`` methods, which means any request that short-circuits
before the AI path (deterministic ALLOW, command_shield catastrophic
BLOCK, future fast-paths) would otherwise inherit stale values from a
prior AI-path request in the same runtime.

These tests pin the fix: the pipeline resets ``last_prompt_id`` on both
engines at the start of ``_process_intent_impl``, giving every request
a clean observability slate.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from action_registry.types import ActionType
from intentframe_core.enums import Decision, Reversibility, RiskLevel
from intentframe_core.types import (
    AnalysisReport,
    ExecutionResult,
    IntentFrame,
    UserContext,
    ValidationResult,
)
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicResult,
)
from intentframe_server.pipeline import IntentFrameRuntime
from policy_registry.models import ActionPermission


def _run(coro):
    return asyncio.run(coro)


def _user_context() -> UserContext:
    return UserContext(
        user_id="test",
        allowed_actions={
            "RUN_COMMAND": ActionPermission(safe=False),
            "READ_EMAIL": ActionPermission(safe=True),
        },
    )


def _run_command_intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.RUN_COMMAND,
        target="curl https://example.com",
        reason="probe",
        agent_id="test_agent",
    )


def _read_email_intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.READ_EMAIL,
        target="inbox",
        reason="check",
        agent_id="test_agent",
    )


def _safe_analysis() -> AnalysisReport:
    return AnalysisReport(
        stated_intent="ok",
        risk_factors={"overall": RiskLevel.LOW},
        reversibility=Reversibility.FULLY_REVERSIBLE,
        confidence=1.0,
        recommendation="ok",
    )


class _StubAE:
    """AE stub that records a ``last_prompt_id`` whenever ``analyze``
    is called — mirroring the real engine's contract, including the
    "set only on AI path" invariant."""

    def __init__(self, prompt_id: str = "critical_generic"):
        self._prompt_id = prompt_id
        self.last_prompt_id: str | None = None

    async def analyze(self, intent, **_kwargs) -> AnalysisReport:
        self.last_prompt_id = self._prompt_id
        return _safe_analysis()


class _StubGuardian:
    """Guardian stub matching the AE stub semantics."""

    def __init__(self, prompt_id: str = "critical"):
        self._prompt_id = prompt_id
        self.last_prompt_id: str | None = None

    async def validate(self, intent, analysis, user_context, **_kwargs):
        self.last_prompt_id = self._prompt_id
        return ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            analysis=analysis,
            message="allowed",
            decision_path="ai_path",
        )


def _make_runtime(deterministic_decide):
    """Build a runtime where the DeterministicGuardian is a MagicMock
    whose ``decide`` side-effect is driven by ``deterministic_decide``
    (called once per ``process_intent`` invocation)."""

    det_guardian = MagicMock()
    det_guardian.decide = MagicMock(side_effect=deterministic_decide)

    executor = MagicMock()
    executor.execute = MagicMock(
        return_value=ExecutionResult(success=True, data={"stdout": "ok"})
    )

    runtime = IntentFrameRuntime(
        analysis_engine=_StubAE(),
        guardian=_StubGuardian(),
        executor=executor,
        deterministic_guardian=det_guardian,
        verbose=False,
    )
    runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)
    return runtime


class TestPromptIdDoesNotLeakAcrossRequests:
    def test_deterministic_allow_after_ai_path_has_no_prompt_ids(self):
        """The exact scenario that surfaced the bug in live traces:

          req 1: RUN_COMMAND → AI path → prompt ids set on engines
          req 2: READ_EMAIL  → deterministic ALLOW → AE + Guardian skipped

        Without the reset, req 2's audit entry inherited req 1's
        prompt ids.  With the reset, req 2's audit entry must be clean.
        """
        calls = iter([
            # req 1 — UNDECIDED so AI path runs
            DeterministicResult(
                decision=DeterministicDecision.UNDECIDED,
                reason="",
                matched_gate="",
            ),
            # req 2 — ALLOW so AE + AIGuardian are skipped entirely
            DeterministicResult(
                decision=DeterministicDecision.ALLOW,
                reason="passive read",
                matched_gate="passive_read",
            ),
        ])
        runtime = _make_runtime(lambda *a, **kw: next(calls))

        _run(runtime.process_intent(_run_command_intent(), _user_context()))
        _run(runtime.process_intent(_read_email_intent(), _user_context()))

        assert len(runtime.audit_log) == 2

        ai_entry = runtime.audit_log[0]
        assert ai_entry["decision_path"] == "ai_path"
        assert ai_entry.get("ae_prompt_id") == "critical_generic"
        assert ai_entry.get("guardian_prompt_id") == "critical"

        det_entry = runtime.audit_log[1]
        assert det_entry["decision_path"] == "deterministic"
        assert "ae_prompt_id" not in det_entry, (
            f"stale ae_prompt_id leaked into deterministic audit entry: "
            f"{det_entry}"
        )
        assert "guardian_prompt_id" not in det_entry, (
            f"stale guardian_prompt_id leaked into deterministic audit "
            f"entry: {det_entry}"
        )

    def test_engines_last_prompt_id_cleared_at_request_start(self):
        """Stronger invariant: the reset happens on the engine objects
        themselves, not just on the audit entry.  This means any future
        consumer reading ``engine.last_prompt_id`` (metrics exporter,
        tracing hook, etc.) also sees a clean state, not just audit."""
        calls = iter([
            DeterministicResult(
                decision=DeterministicDecision.UNDECIDED,
                reason="",
                matched_gate="",
            ),
            DeterministicResult(
                decision=DeterministicDecision.ALLOW,
                reason="passive read",
                matched_gate="passive_read",
            ),
        ])
        runtime = _make_runtime(lambda *a, **kw: next(calls))

        _run(runtime.process_intent(_run_command_intent(), _user_context()))
        assert runtime.analysis_engine.last_prompt_id == "critical_generic"
        assert runtime.guardian.last_prompt_id == "critical"

        _run(runtime.process_intent(_read_email_intent(), _user_context()))
        assert runtime.analysis_engine.last_prompt_id is None
        assert runtime.guardian.last_prompt_id is None

    def test_deterministic_block_after_ai_path_has_no_prompt_ids(self):
        """Deterministic BLOCK emits its own audit entry earlier in the
        pipeline; it must also start from a reset state so prompt ids
        from a prior AI request can't leak into a subsequent BLOCK."""
        calls = iter([
            DeterministicResult(
                decision=DeterministicDecision.UNDECIDED,
                reason="",
                matched_gate="",
            ),
            DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason="disallowed",
                matched_gate="permission",
            ),
        ])
        runtime = _make_runtime(lambda *a, **kw: next(calls))

        _run(runtime.process_intent(_run_command_intent(), _user_context()))
        _run(runtime.process_intent(_read_email_intent(), _user_context()))

        det_entry = runtime.audit_log[1]
        assert det_entry["decision"] == "BLOCK"
        assert det_entry["decision_path"] == "deterministic"
        assert "ae_prompt_id" not in det_entry
        assert "guardian_prompt_id" not in det_entry
        assert runtime.analysis_engine.last_prompt_id is None
        assert runtime.guardian.last_prompt_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
