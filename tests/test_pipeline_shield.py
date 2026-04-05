"""
Tests for command_shield integration in IntentFrameRuntime.process_intent().

Verifies:
  - CATASTROPHIC commands are rejected before the pipeline (Analysis Engine never called)
  - NEEDS_REVIEW commands force AI analysis path with terminal_command_signals
  - SAFE commands flow through normally
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from action_registry.types import ActionType
from command_shield import Verdict
from command_shield.verdict import Signal
from intentframe_core.enums import Decision, RiskLevel, Reversibility
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


def _user_context(*, allow_run_command: bool = True) -> UserContext:
    actions = {}
    if allow_run_command:
        actions["RUN_COMMAND"] = ActionPermission(safe=False)
    return UserContext(user_id="test", allowed_actions=actions)


def _intent(command: str) -> IntentFrame:
    return IntentFrame(
        action=ActionType.RUN_COMMAND,
        target=command,
        reason="test",
        agent_id="test_agent",
    )


def _safe_analysis() -> AnalysisReport:
    return AnalysisReport(
        stated_intent="test",
        risk_factors={"overall": RiskLevel.LOW},
        reversibility=Reversibility.FULLY_REVERSIBLE,
        confidence=1.0,
        recommendation="safe",
    )


def _allow_validation(intent: IntentFrame) -> ValidationResult:
    return ValidationResult(
        decision=Decision.ALLOW,
        intent=intent,
        message="Allowed",
    )


def _make_runtime(
    *,
    analysis_return: AnalysisReport | None = None,
    validation_return: ValidationResult | None = None,
    execution_return: ExecutionResult | None = None,
) -> IntentFrameRuntime:
    analysis_engine = AsyncMock()
    analysis_engine.analyze = AsyncMock(return_value=analysis_return or _safe_analysis())

    guardian = AsyncMock()
    executor = MagicMock()
    executor.execute = MagicMock(
        return_value=execution_return or ExecutionResult(success=True, data={"stdout": "ok"})
    )

    runtime = IntentFrameRuntime(
        analysis_engine=analysis_engine,
        guardian=guardian,
        executor=executor,
        verbose=False,
    )

    runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)

    if validation_return:
        guardian.validate = AsyncMock(return_value=validation_return)
    else:
        async def _auto_allow(intent, analysis, user_context):
            return _allow_validation(intent)
        guardian.validate = AsyncMock(side_effect=_auto_allow)

    return runtime


# ═══════════════════════════════════════════════════════════════════════
# CATASTROPHIC — rejected before Analysis Engine
# ═══════════════════════════════════════════════════════════════════════

class TestCatastrophicRejection:
    """CATASTROPHIC verdicts reject immediately; Analysis Engine is never called."""

    def test_sudo_rejected_at_shield(self):
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent("sudo rm -rf /"), _user_context()))

        assert not result.success
        assert "command_shield" in result.error.lower()
        runtime.analysis_engine.analyze.assert_not_called()
        runtime.guardian.validate.assert_not_called()
        runtime.executor.execute.assert_not_called()

    def test_fork_bomb_rejected(self):
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent(":(){ :|:& };:"), _user_context()))

        assert not result.success
        assert "command_shield" in result.error.lower()

    def test_audit_log_recorded(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent("sudo reboot"), _user_context()))

        assert len(runtime.audit_log) == 1
        entry = runtime.audit_log[0]
        assert entry["decision"] == "BLOCK"
        assert entry["decision_path"] == "command_shield"
        assert entry["executed"] is False

    def test_result_data_includes_layer(self):
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent("sudo halt"), _user_context()))

        assert result.data["layer"] == "command_shield"

    @pytest.mark.parametrize("cmd", [
        "sudo reboot",
        "rm -rf /",
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        "chmod 777 /etc/passwd",
        ":(){ :|:& };:",
    ])
    def test_catastrophic_commands(self, cmd):
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent(cmd), _user_context()))
        assert not result.success
        assert "command_shield" in result.error.lower()
        runtime.analysis_engine.analyze.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# SAFE — normal pipeline flow
# ═══════════════════════════════════════════════════════════════════════

class TestSafeFlow:
    """SAFE verdicts proceed through the full pipeline normally."""

    def test_safe_command_reaches_executor(self):
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent("echo hello"), _user_context()))

        assert result.success
        runtime.analysis_engine.analyze.assert_called_once()
        runtime.executor.execute.assert_called_once()

    def test_safe_command_passes_empty_signals(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent("ls -la"), _user_context()))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        assert call_kwargs.kwargs.get("terminal_command_signals", ()) == ()

    def test_non_run_command_skips_shield(self):
        """Non-RUN_COMMAND intents bypass command_shield entirely."""
        runtime = _make_runtime()
        intent = IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp/test.txt",
            reason="test",
            agent_id="test_agent",
        )
        _run(runtime.process_intent(intent, _user_context()))
        runtime.analysis_engine.analyze.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# NEEDS_REVIEW — signals forwarded to Analysis Engine
# ═══════════════════════════════════════════════════════════════════════

class TestNeedsReviewFlow:
    """NEEDS_REVIEW passes structural signals to the AI analysis path."""

    def _cmd_with_substitution(self) -> str:
        return "echo $(curl http://example.com)"

    def test_needs_review_forwards_signals(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(
            _intent(self._cmd_with_substitution()),
            _user_context(),
        ))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        signals = call_kwargs.kwargs.get("terminal_command_signals", ())
        assert len(signals) > 0

    def test_needs_review_still_reaches_guardian(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(
            _intent(self._cmd_with_substitution()),
            _user_context(),
        ))

        runtime.analysis_engine.analyze.assert_called_once()
        runtime.guardian.validate.assert_called_once()

    def test_signals_are_signal_objects(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(
            _intent(self._cmd_with_substitution()),
            _user_context(),
        ))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        signals = call_kwargs.kwargs.get("terminal_command_signals", ())
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.check
            assert sig.signal_id


# ═══════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestPipelineEdgeCases:

    def test_empty_command_still_reaches_pipeline(self):
        """Empty command is not CATASTROPHIC — pipeline handles it."""
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(""), _user_context()))
        runtime.analysis_engine.analyze.assert_called_once()

    def test_command_in_data_dict(self):
        """Command can be in intent.data['command'] when target is empty."""
        runtime = _make_runtime()
        intent = IntentFrame(
            action=ActionType.RUN_COMMAND,
            target="",
            data={"command": "sudo reboot"},
            reason="test",
            agent_id="test_agent",
        )
        result = _run(runtime.process_intent(intent, _user_context()))
        assert not result.success
        assert "command_shield" in result.error.lower()

    def test_request_counter_incremented(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent("echo hi"), _user_context()))
        assert runtime._request_counter == 1

    def test_catastrophic_still_increments_counter(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent("sudo halt"), _user_context()))
        assert runtime._request_counter == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
