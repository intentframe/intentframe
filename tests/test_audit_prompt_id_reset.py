"""Regression: prompt forensic audit fields must never leak across requests.

Prompt evidence now rides on the per-request AnalysisReport/ValidationResult
objects. Any request that short-circuits before the AI path must not inherit
evidence from a prior request in the same runtime.
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
    PromptEvidence,
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
        data={"command": "curl https://example.com"},
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
    """AE stub that returns prompt evidence whenever ``analyze`` is called."""

    def __init__(self, prompt_label: str = "critical_run_command"):
        self._prompt_label = prompt_label

    async def analyze(self, intent, **_kwargs) -> AnalysisReport:
        report = _safe_analysis()
        report.prompt_evidence = PromptEvidence(
            prompt_source="bundle",
            prompt_label=self._prompt_label,
            system_prompt="ae system prompt",
            request_prompt="ae request prompt",
            llm_output={"stated_intent": "ok"},
            converted_output=report.model_dump(
                mode="json",
                exclude={"prompt_evidence": True},
            ),
        )
        return report


class _StubGuardian:
    """Guardian stub matching the AE stub semantics."""

    def __init__(self, prompt_label: str = "fallback_default"):
        self._prompt_label = prompt_label

    async def validate(self, intent, analysis, user_context, **_kwargs):
        validation = ValidationResult(
            decision=Decision.ALLOW,
            intent=intent,
            analysis=analysis,
            message="allowed",
            decision_path="ai_path",
        )
        validation.prompt_evidence = PromptEvidence(
            prompt_source="fallback_default",
            prompt_label=self._prompt_label,
            system_prompt="guardian system prompt",
            request_prompt="guardian request prompt",
            llm_output={"decision": "ALLOW"},
            converted_output=validation.model_dump(
                mode="json",
                exclude={
                    "prompt_evidence": True,
                    "analysis": {"prompt_evidence": True},
                },
            ),
        )
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

    def test_prompt_evidence_is_per_request_return_data_not_engine_state(self):
        """Prompt evidence is no longer reset on long-lived engine objects.

        The invariant is stronger now: skipped paths have no returned evidence
        to audit, so stale evidence cannot leak from prior engine state.
        """
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

        _run(runtime.process_intent(_read_email_intent(), _user_context()))
        det_entry = runtime.audit_log[1]
        assert "ae_prompt_label" not in det_entry
        assert "guardian_prompt_label" not in det_entry
        assert "ae_llm_output" not in det_entry
        assert "guardian_converted_output" not in det_entry
        assert not hasattr(runtime.analysis_engine, "last_prompt_label")
        assert not hasattr(runtime.guardian, "last_prompt_label")

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
        assert "ae_llm_output" not in det_entry
        assert "guardian_converted_output" not in det_entry


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
