"""Regression: prompt forensic audit fields must never leak
across requests.

The AE and Guardian engines expose the source/label plus full system and
request prompts that the pipeline copies into the audit entry. Any request
that short-circuits before the AI path must not inherit stale forensic
evidence from a prior request in the same runtime.
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
    """AE stub that records prompt evidence whenever ``analyze`` is called."""

    def __init__(self, prompt_label: str = "critical_run_command"):
        self._prompt_label = prompt_label
        self.last_prompt_source: str | None = None
        self.last_prompt_label: str | None = None
        self.last_system_prompt: str | None = None
        self.last_request_prompt: str | None = None

    async def analyze(self, intent, **_kwargs) -> AnalysisReport:
        self.last_prompt_source = "bundle"
        self.last_prompt_label = self._prompt_label
        self.last_system_prompt = "ae system prompt"
        self.last_request_prompt = "ae request prompt"
        report = _safe_analysis()
        self.last_llm_output = {"stated_intent": "ok"}
        self.last_converted_output = report.model_dump(mode="json")
        return report


class _StubGuardian:
    """Guardian stub matching the AE stub semantics."""

    def __init__(self, prompt_label: str = "fallback_default"):
        self._prompt_label = prompt_label
        self.last_prompt_source: str | None = None
        self.last_prompt_label: str | None = None
        self.last_system_prompt: str | None = None
        self.last_request_prompt: str | None = None

    async def validate(self, intent, analysis, user_context, **_kwargs):
        self.last_prompt_source = "fallback_default"
        self.last_prompt_label = self._prompt_label
        self.last_system_prompt = "guardian system prompt"
        self.last_request_prompt = "guardian request prompt"
        validation = ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            analysis=analysis,
            message="allowed",
            decision_path="ai_path",
        )
        self.last_llm_output = {"decision": "ALLOW"}
        self.last_converted_output = validation.model_dump(mode="json")
        return validation


def _make_runtime(deterministic_decide):
    """Build a runtime where the DeterministicGuardian is a MagicMock
    whose ``decide_async`` side-effect is driven by ``deterministic_decide``
    (called once per ``process_intent`` invocation)."""

    det_guardian = MagicMock()
    det_guardian.decide_async = AsyncMock(side_effect=deterministic_decide)

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


class TestPromptEvidenceDoesNotLeakAcrossRequests:
    def test_deterministic_allow_after_ai_path_has_no_prompt_evidence(self):
        """The exact scenario that surfaced the bug in live traces:

          req 1: RUN_COMMAND → AI path → prompt evidence set on engines
          req 2: READ_EMAIL  → deterministic ALLOW → AE + Guardian skipped

        Without the reset, req 2's audit entry inherited req 1's
        prompt evidence. With the reset, req 2's audit entry must be clean.
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
        assert ai_entry.get("ae_prompt_source") == "bundle"
        assert ai_entry.get("ae_prompt_label") == "critical_run_command"
        assert ai_entry.get("ae_system_prompt") == "ae system prompt"
        assert ai_entry.get("ae_request_prompt") == "ae request prompt"
        assert ai_entry.get("guardian_prompt_source") == "fallback_default"
        assert ai_entry.get("guardian_prompt_label") == "fallback_default"
        assert ai_entry.get("guardian_system_prompt") == "guardian system prompt"
        assert ai_entry.get("guardian_request_prompt") == "guardian request prompt"
        assert ai_entry.get("ae_llm_output") == {"stated_intent": "ok"}
        assert ai_entry.get("guardian_llm_output") == {"decision": "ALLOW"}
        assert ai_entry.get("ae_converted_output") is not None
        assert ai_entry.get("guardian_converted_output") is not None

        det_entry = runtime.audit_log[1]
        assert det_entry["decision_path"] == "deterministic"
        assert "ae_prompt_label" not in det_entry
        assert "ae_system_prompt" not in det_entry
        assert "ae_request_prompt" not in det_entry
        assert "guardian_prompt_label" not in det_entry
        assert "guardian_system_prompt" not in det_entry
        assert "guardian_request_prompt" not in det_entry
        assert "ae_llm_output" not in det_entry
        assert "guardian_converted_output" not in det_entry

    def test_engines_last_prompt_evidence_cleared_at_request_start(self):
        """Stronger invariant: the reset happens on the engine objects
        themselves, not just on the audit entry.  This means any future
        consumer reading prompt evidence (metrics exporter,
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
        assert runtime.analysis_engine.last_prompt_label == "critical_run_command"
        assert runtime.analysis_engine.last_system_prompt == "ae system prompt"
        assert runtime.guardian.last_prompt_label == "fallback_default"
        assert runtime.guardian.last_system_prompt == "guardian system prompt"

        _run(runtime.process_intent(_read_email_intent(), _user_context()))
        assert runtime.analysis_engine.last_prompt_label is None
        assert runtime.analysis_engine.last_system_prompt is None
        assert runtime.guardian.last_prompt_label is None
        assert runtime.guardian.last_system_prompt is None
        assert runtime.analysis_engine.last_llm_output is None
        assert runtime.guardian.last_converted_output is None

    def test_deterministic_block_after_ai_path_has_no_prompt_evidence(self):
        """Deterministic BLOCK emits its own audit entry earlier in the
        pipeline; it must also start from a reset state so prompt evidence
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
        assert "ae_prompt_label" not in det_entry
        assert "guardian_prompt_label" not in det_entry
        assert runtime.analysis_engine.last_prompt_label is None
        assert runtime.guardian.last_prompt_label is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
