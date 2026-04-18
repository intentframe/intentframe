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
    CommandIntel,
    ExecutionContext,
    ExecutionResult,
    IntentFrame,
    UserContext,
    ValidationResult,
)
from intentframe_server.pipeline import IntentFrameRuntime
from policy_registry.models import ActionPermission


def _run(coro):
    return asyncio.run(coro)


def _user_context(
    *,
    allow_run_command: bool = True,
    extra: dict[str, ActionPermission] | None = None,
) -> UserContext:
    actions: dict[str, ActionPermission] = {}
    if allow_run_command:
        actions["RUN_COMMAND"] = ActionPermission(safe=False)
    if extra:
        actions.update(extra)
    return UserContext(user_id="test", allowed_actions=actions)


# Commands chosen for pipeline-flow tests:
#
#   CMD_READ_ONLY — DG will ALLOW (capability:read_only:*).  AE and
#                   AIGuardian are skipped — use this to verify the
#                   fast-path behavior.
#   CMD_UNDECIDED — SAFE verdict but no read_only cap AND no other
#                   fast-path-triggering capability, so DG falls
#                   through to UNDECIDED.  AE + AIGuardian are both
#                   invoked — use this when a test needs to assert on
#                   their call kwargs.  NOTE: bare chains/pipes like
#                   `echo hi && echo bye` no longer qualify — they
#                   now emit `capability:read_only:composition` and
#                   take the fast-path.  Use a command whose head is
#                   not in any capability rule instead.
#   CMD_NEEDS_REVIEW — shell substitution → NEEDS_REVIEW verdict, signals
#                      flow through, AE + AIGuardian invoked.
CMD_READ_ONLY = "echo hello"
CMD_UNDECIDED = "mkdir newdir"
CMD_NEEDS_REVIEW = "echo $(curl http://example.com)"


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
        async def _auto_allow(intent, analysis, user_context, **kwargs):
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
    """SAFE verdicts proceed through the full pipeline — either via
    the DG ALLOW fast-path or the UNDECIDED → AE + AIGuardian path."""

    def test_read_only_safe_command_reaches_executor(self):
        """CMD_READ_ONLY takes the DG fast-path: AE and AIGuardian
        are skipped, executor still runs."""
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent(CMD_READ_ONLY), _user_context()))

        assert result.success
        runtime.analysis_engine.analyze.assert_not_called()
        runtime.guardian.validate.assert_not_called()
        runtime.executor.execute.assert_called_once()

    def test_undecided_safe_command_reaches_full_pipeline(self):
        """CMD_UNDECIDED lands in UNDECIDED — AE and AIGuardian are
        both invoked before the executor runs."""
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        assert result.success
        runtime.analysis_engine.analyze.assert_called_once()
        runtime.guardian.validate.assert_called_once()
        runtime.executor.execute.assert_called_once()

    def test_undecided_safe_command_forwards_signals_to_ae(self):
        """Gap 1: signal forwarding is observable on UNDECIDED
        commands (when AE is actually invoked).  Fast-pathed
        commands naturally don't observe this because AE is
        skipped — that's the whole point."""
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        assert "terminal_command_signals" in call_kwargs.kwargs

    def test_non_run_command_skips_shield(self):
        """Non-RUN_COMMAND intents bypass command_shield entirely.
        Use safe=False so DG's passive-read fast-path doesn't fire
        and AE is still invoked (what we're asserting on)."""
        runtime = _make_runtime()
        intent = IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp/test.txt",
            reason="test",
            agent_id="test_agent",
        )
        user = _user_context(
            allow_run_command=False,
            extra={"READ_FILE": ActionPermission(safe=False)},
        )
        _run(runtime.process_intent(intent, user))
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


# ═══════════════════════════════════════════════════════════════════════
# ExecutionContext plumbing
# ═══════════════════════════════════════════════════════════════════════

class TestExecutionContextPlumbing:
    """ExecutionContext is threaded through to analyze and validate."""

    def _make_root_runtime(self) -> IntentFrameRuntime:
        root_ctx = ExecutionContext(
            executor_running_as_root=True,
            executor_uid=0,
            executor_euid=0,
        )
        analysis_engine = AsyncMock()
        analysis_engine.analyze = AsyncMock(return_value=_safe_analysis())

        guardian = AsyncMock()
        executor = MagicMock()
        executor.execute = MagicMock(
            return_value=ExecutionResult(success=True, data={"stdout": "ok"})
        )

        runtime = IntentFrameRuntime(
            analysis_engine=analysis_engine,
            guardian=guardian,
            executor=executor,
            execution_context=root_ctx,
            verbose=False,
        )
        runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)

        async def _auto_allow(intent, analysis, user_context, **kwargs):
            return _allow_validation(intent)
        guardian.validate = AsyncMock(side_effect=_auto_allow)

        return runtime

    def test_analyze_receives_execution_context(self):
        runtime = self._make_root_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        ctx = call_kwargs.kwargs.get("execution_context")
        assert ctx is not None
        assert ctx.executor_running_as_root is True
        assert ctx.executor_euid == 0

    def test_validate_receives_execution_context(self):
        runtime = self._make_root_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        call_kwargs = runtime.guardian.validate.call_args
        ctx = call_kwargs.kwargs.get("execution_context")
        assert ctx is not None
        assert ctx.executor_running_as_root is True

    def test_default_execution_context_is_non_root(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        ctx = call_kwargs.kwargs.get("execution_context")
        assert ctx is not None
        assert ctx.executor_running_as_root is False
        assert ctx.executor_euid == -1

    def test_execution_context_is_frozen(self):
        ctx = ExecutionContext(executor_running_as_root=True, executor_uid=0, executor_euid=0)
        with pytest.raises(Exception):
            ctx.executor_running_as_root = False


# ═══════════════════════════════════════════════════════════════════════
# CommandIntel plumbing (Phase 1)
# ═══════════════════════════════════════════════════════════════════════

class TestCommandIntelPlumbing:
    """Pipeline always builds CommandIntel for RUN_COMMAND and forwards
    it to both AE and AIGuardian when they're invoked.

    After the pre-AE deterministic pass, AE + AIGuardian are only called
    when DG returns UNDECIDED.  We use ``CMD_UNDECIDED`` for assertions
    that need to observe AE/Guardian call kwargs; fast-pathed commands
    skip both (that's the whole point — no AE call to inspect).
    """

    def _intel_from(self, engine_or_guardian) -> CommandIntel | None:
        call_kwargs = engine_or_guardian.call_args
        return call_kwargs.kwargs.get("command_intel")

    def test_undecided_command_forwards_command_intel_to_ae(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        intel = self._intel_from(runtime.analysis_engine.analyze)
        assert intel is not None
        assert intel.verdict == Verdict.SAFE.value

    def test_undecided_command_forwards_command_intel_to_guardian(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        intel = self._intel_from(runtime.guardian.validate)
        assert intel is not None
        assert intel.verdict == Verdict.SAFE.value

    def test_needs_review_forwards_command_intel(self):
        runtime = _make_runtime()
        _run(runtime.process_intent(
            _intent(CMD_NEEDS_REVIEW),
            _user_context(),
        ))

        intel_ae = self._intel_from(runtime.analysis_engine.analyze)
        intel_gu = self._intel_from(runtime.guardian.validate)
        assert intel_ae is not None
        assert intel_gu is not None
        assert intel_ae.verdict == intel_gu.verdict

    def test_undecided_signals_forwarded_to_ae(self):
        """SAFE-verdict UNDECIDED commands still route their signals
        through to AE — Gap 1 forwards them regardless of verdict,
        and DG's UNDECIDED path doesn't eat them."""
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        call_kwargs = runtime.analysis_engine.analyze.call_args
        assert "terminal_command_signals" in call_kwargs.kwargs

    def test_non_run_command_does_not_build_command_intel(self):
        """Non-RUN_COMMAND intents never pay the shield cost.
        Use safe=False so DG falls through to AE and we can observe
        the command_intel kwarg."""
        runtime = _make_runtime()
        intent = IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp/test.txt",
            reason="test",
            agent_id="test_agent",
        )
        user = _user_context(
            allow_run_command=False,
            extra={"READ_FILE": ActionPermission(safe=False)},
        )
        _run(runtime.process_intent(intent, user))

        intel = self._intel_from(runtime.analysis_engine.analyze)
        assert intel is None

    def test_command_intel_is_bounded(self):
        huge_caps = tuple(f"capability:x{i}:y" for i in range(5000))
        intel = CommandIntel(capabilities=huge_caps)
        assert len(intel.capabilities) <= 64

    def test_command_intel_is_frozen(self):
        intel = CommandIntel(verdict="SAFE")
        with pytest.raises(Exception):
            intel.verdict = "CATASTROPHIC"


# ═══════════════════════════════════════════════════════════════════════
# DeterministicGuardian pipeline wiring (pre-AE deterministic pass)
# ═══════════════════════════════════════════════════════════════════════

class TestDeterministicGuardianPipelineFlow:
    """End-to-end wiring of DG into the pipeline.

    We assert:
      - DG ALLOW short-circuits AE + AIGuardian but still runs executor.
      - DG BLOCK short-circuits AE + AIGuardian AND executor.
      - DG UNDECIDED produces the full pipeline (AE + AIGuardian + executor).
      - Audit log uses decision_path="deterministic" for DG decisions.
    """

    def test_read_only_command_is_allowed_by_dg(self):
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent(CMD_READ_ONLY), _user_context()))

        assert result.success
        runtime.analysis_engine.analyze.assert_not_called()
        runtime.guardian.validate.assert_not_called()
        runtime.executor.execute.assert_called_once()

        entry = runtime.audit_log[-1]
        assert entry["decision_path"] == "deterministic"
        assert entry["decision"] == "ALLOW"
        assert entry["matched_gate"] == "run_command_read_only"

    def test_passive_read_is_allowed_by_dg(self):
        """READ_FILE marked safe takes the DG passive-read fast-path."""
        runtime = _make_runtime()
        intent = IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp/x.txt",
            reason="test",
            agent_id="t",
        )
        user = _user_context(
            allow_run_command=False,
            extra={"READ_FILE": ActionPermission(safe=True)},
        )
        result = _run(runtime.process_intent(intent, user))

        assert result.success
        runtime.analysis_engine.analyze.assert_not_called()
        runtime.guardian.validate.assert_not_called()
        runtime.executor.execute.assert_called_once()

        entry = runtime.audit_log[-1]
        assert entry["decision_path"] == "deterministic"
        assert entry["matched_gate"] == "passive_read"

    def test_permission_block_is_deterministic(self):
        """An action outside allowed_actions BLOCKs at DG before AE runs."""
        runtime = _make_runtime()
        intent = IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp/x.txt",
            reason="test",
            agent_id="t",
        )
        result = _run(runtime.process_intent(intent, _user_context()))
        # _user_context() does NOT allow READ_FILE

        assert not result.success
        runtime.analysis_engine.analyze.assert_not_called()
        runtime.guardian.validate.assert_not_called()
        runtime.executor.execute.assert_not_called()

        assert runtime.audit_log[-1]["decision"] == "BLOCK"
        assert runtime.audit_log[-1]["decision_path"] == "deterministic"
        assert runtime.audit_log[-1]["matched_gate"] == "permission"

    def test_constraint_block_is_deterministic(self):
        """blocked_patterns BLOCK happens at DG, before AE runs."""
        from policy_registry.constraints.terminal import TerminalConstraints

        runtime = _make_runtime()
        user = UserContext(
            user_id="t",
            allowed_actions={
                "RUN_COMMAND": ActionPermission(
                    safe=False,
                    constraints=TerminalConstraints(blocked_patterns=["rm "]),
                ),
            },
        )
        result = _run(runtime.process_intent(_intent("rm file.txt"), user))

        assert not result.success
        runtime.analysis_engine.analyze.assert_not_called()
        runtime.guardian.validate.assert_not_called()
        runtime.executor.execute.assert_not_called()

        entry = runtime.audit_log[-1]
        assert entry["decision"] == "BLOCK"
        assert entry["decision_path"] == "deterministic"
        assert entry["matched_gate"] == "constraint"

    def test_undecided_command_invokes_ae_and_guardian(self):
        """CMD_UNDECIDED has no read_only tag and no blocked pattern —
        DG returns UNDECIDED and the full pipeline runs."""
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent(CMD_UNDECIDED), _user_context()))

        assert result.success
        runtime.analysis_engine.analyze.assert_called_once()
        runtime.guardian.validate.assert_called_once()
        runtime.executor.execute.assert_called_once()

    def test_catastrophic_still_blocks_before_dg(self):
        """command_shield CATASTROPHIC pre-empts DG entirely."""
        runtime = _make_runtime()
        result = _run(runtime.process_intent(_intent("sudo rm -rf /"), _user_context()))

        assert not result.success
        entry = runtime.audit_log[-1]
        # command_shield path, not deterministic — CATASTROPHIC fires first
        assert entry["decision_path"] == "command_shield"

    def test_dg_allow_produces_synthetic_analysis_report(self):
        """DG ALLOW synthesizes a minimal AnalysisReport for audit
        formatting.  Verifying that the synthesized report is present
        ensures downstream consumers (logs, metrics) can still read
        ``audit_entry["risk_level"]`` etc. without None-guards."""
        runtime = _make_runtime()
        _run(runtime.process_intent(_intent(CMD_READ_ONLY), _user_context()))

        entry = runtime.audit_log[-1]
        # risk_level and confidence must be present from the synthetic
        # report — the ALLOW branch below them in the pipeline reads
        # both for audit.
        assert "risk_level" in entry
        assert "confidence" in entry
        assert entry["confidence"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
