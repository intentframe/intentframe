"""Policy hardening tests — §8.1 exception fail-closed and §8.2 missing-checker skip.

Complements ``test_deterministic_guardian.py::TestFailClosedExceptionHandling``,
``test_pipeline_shield.py::TestDgExceptionFailClosed``, and
``test_constraint_checker_skipped.py``.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from action_registry.types import ActionType
from intentframe_action_bundle.evidence import CommandIntel
from intentframe_action_bundle.bundles.terminal import TerminalActionBundle
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicGuardian,
)
from intentframe_core.enums import Decision
from intentframe_core.types import ExecutionResult, IntentFrame, UserContext, ValidationResult
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import BundleContext
from policy_registry.constraints.calendar import CalendarConstraints
from policy_registry.constraints.terminal import TerminalConstraints
from policy_registry.models import ActionPermission
from tests.deterministic_accuracy._helpers import decide_dg_sync, run_dg_with_intel


# ── §8.1 Exception fail-closed ─────────────────────────────────────


class TestExceptionFailClosedPolicy:
    def test_prepare_evidence_exception_blocks_with_dg_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def boom(self, intent, permission, ctx, *, verbose=False):
            del self, intent, permission, verbose
            raise ValueError("shield blew up")

        monkeypatch.setattr(TerminalActionBundle, "prepare_evidence", boom)

        dg = DeterministicGuardian()
        result = decide_dg_sync(
            dg,
            IntentFrame(
                action=ActionType.RUN_COMMAND,
                target="echo hi",
                reason="test",
                agent_id="a",
            ),
            UserContext(
                user_id="u",
                allowed_actions={"RUN_COMMAND": ActionPermission(safe=False)},
            ),
        )

        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "exception"
        assert result.dg_exception == "ValueError('shield blew up')"
        assert result.decision_path == "deterministic"

    def test_permission_block_has_no_dg_exception(self) -> None:
        dg = DeterministicGuardian()
        result = decide_dg_sync(
            dg,
            IntentFrame(
                action=ActionType.READ_FILE,
                target="/tmp/x",
                reason="test",
                agent_id="a",
            ),
            UserContext(user_id="u", allowed_actions={}),
        )

        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "permission"
        assert result.dg_exception == ""

    def test_constraint_block_has_no_dg_exception(self) -> None:
        dg = DeterministicGuardian()
        constraints = TerminalConstraints(blocked_patterns=["sudo"])
        result = run_dg_with_intel(
            "sudo ls",
            UserContext(
                user_id="u",
                allowed_actions={
                    "RUN_COMMAND": ActionPermission(safe=False, constraints=constraints),
                },
            ),
            CommandIntel(verdict="SAFE", capabilities=()),
            dg,
        )

        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "constraint"
        assert result.dg_exception == ""

    def test_pipeline_permission_block_audit_omits_dg_exception(self) -> None:
        from intentframe_server.pipeline import IntentFrameRuntime

        runtime = IntentFrameRuntime(
            analysis_engine=AsyncMock(),
            guardian=AsyncMock(),
            executor=MagicMock(),
            verbose=False,
        )
        runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)

        intent = IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp/x",
            reason="test",
            agent_id="a",
        )
        asyncio.run(runtime.process_intent(intent, UserContext(user_id="u", allowed_actions={})))

        entry = runtime.audit_log[-1]
        assert entry["decision"] == "BLOCK"
        assert entry["matched_gate"] == "permission"
        assert "dg_exception" not in entry
        runtime.analysis_engine.analyze.assert_not_called()


# ── §8.2 Missing constraint checker skip ─────────────────────────────


class TestMissingConstraintCheckerPolicy:
    def test_wired_checker_does_not_set_constraint_checker_skipped(self) -> None:
        dg = DeterministicGuardian()
        constraints = TerminalConstraints(blocked_patterns=["rm -rf"])
        result = run_dg_with_intel(
            "echo safe",
            UserContext(
                user_id="u",
                allowed_actions={
                    "RUN_COMMAND": ActionPermission(safe=False, constraints=constraints),
                },
            ),
            CommandIntel(verdict="SAFE", capabilities=()),
            dg,
        )

        assert result.decision is DeterministicDecision.UNDECIDED
        assert result.bundle_context is not None
        assert result.bundle_context.constraint_checker_skipped is None

    def test_logging_warning_on_missing_checker(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from intentframe_bundle_sdk.action import NullActionBundle

        caplog.set_level(logging.WARNING)
        bundle = NullActionBundle()
        ctx = BundleContext(
            intent=IntentFrame(
                action=ActionType.CREATE_EVENT,
                target="work",
                reason="test",
                agent_id="a",
            )
        )
        permission = ActionPermission(
            safe=False,
            constraints=CalendarConstraints(allowed_calendars=["work"]),
        )

        bundle.check_policy(ctx.intent, permission, ctx)

        assert any(
            "CalendarConstraints" in rec.message and "CONSTRAINT_CHECKERS" in rec.message
            for rec in caplog.records
        )

    def test_runner_verbose_prints_constraint_checker_skipped(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from intentframe_action_bundle.bundles.register import ensure_bundles_registered
        from intentframe_bundle_sdk.registry import action_bundle_for

        ensure_bundles_registered()
        intent = IntentFrame(
            action=ActionType.CREATE_EVENT,
            target="work",
            reason="test",
            agent_id="a",
        )
        permission = ActionPermission(
            safe=False,
            constraints=CalendarConstraints(allowed_calendars=["work"]),
        )
        bundle = action_bundle_for("CREATE_EVENT", permission)
        user = UserContext(
            user_id="u",
            allowed_actions={"CREATE_EVENT": permission},
        )

        asyncio.run(
            DeterministicRunner.run_action_bundle(
                bundle,
                intent,
                permission,
                user,
                verbose=True,
            )
        )

        out = capsys.readouterr().out
        assert "constraint checker skipped: CalendarConstraints" in out

    def test_undecided_pipeline_audit_includes_constraint_checker_skipped(self) -> None:
        from intentframe_core.types import AnalysisReport
        from intentframe_core.enums import Reversibility, RiskLevel
        from intentframe_server.pipeline import IntentFrameRuntime

        runtime = IntentFrameRuntime(
            analysis_engine=AsyncMock(),
            guardian=AsyncMock(),
            executor=MagicMock(),
            verbose=False,
        )
        runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)
        runtime.analysis_engine.analyze = AsyncMock(
            return_value=AnalysisReport(
                stated_intent="create",
                risk_factors={"overall": RiskLevel.LOW},
                reversibility=Reversibility.FULLY_REVERSIBLE,
                confidence=0.9,
                recommendation="ok",
            )
        )
        runtime.guardian.validate = AsyncMock(
            return_value=ValidationResult(
                decision=Decision.BLOCK,
                intent=IntentFrame(
                    action=ActionType.CREATE_EVENT,
                    target="work",
                    reason="test",
                    agent_id="a",
                ),
                message="blocked by guardian test",
            )
        )

        intent = IntentFrame(
            action=ActionType.CREATE_EVENT,
            target="work",
            reason="test",
            agent_id="a",
        )
        user = UserContext(
            user_id="u",
            allowed_actions={
                "CREATE_EVENT": ActionPermission(
                    safe=False,
                    constraints=CalendarConstraints(allowed_calendars=["work"]),
                ),
            },
        )

        asyncio.run(runtime.process_intent(intent, user))

        entry = runtime.audit_log[-1]
        assert entry["constraint_checker_skipped"] == "CalendarConstraints"
        assert entry["decision"] == "BLOCK"
        runtime.analysis_engine.analyze.assert_called_once()
        runtime.guardian.validate.assert_called_once()
        runtime.executor.execute.assert_not_called()

    def test_startup_registry_still_allowlists_only_calendar(self) -> None:
        from tests.test_bundle_constraint_registry import (
            ALL_ACTION_CONSTRAINT_TYPES,
            KNOWN_UNMAPPED_CONSTRAINT_TYPES,
            WIRED_CONSTRAINT_TYPES,
        )

        assert CalendarConstraints in KNOWN_UNMAPPED_CONSTRAINT_TYPES
        assert len(KNOWN_UNMAPPED_CONSTRAINT_TYPES) == 1
        assert WIRED_CONSTRAINT_TYPES | KNOWN_UNMAPPED_CONSTRAINT_TYPES == ALL_ACTION_CONSTRAINT_TYPES
