"""Policy hardening tests — exception fail-closed and constraint enforcement."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from intentframe_native_kit.action_registry.types import ActionType
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicGuardian,
)
from intentframe_core.types import ExecutionResult, IntentFrame, UserContext
from policy_registry.models import ActionPermission
from tests._bundle_loader import make_deterministic_guardian
from tests.deterministic_accuracy._helpers import decide_dg_sync, run_dg_with_intel


class TestExceptionFailClosedPolicy:
    def test_prepare_evidence_exception_blocks_with_dg_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def boom(self, intent, ctx, *, verbose=False):
            del self, intent, ctx, verbose
            raise ValueError("shield blew up")

        monkeypatch.setattr(TerminalActionBundle, "prepare_evidence", boom)

        dg = make_deterministic_guardian()
        result = decide_dg_sync(
            dg,
            IntentFrame(
                action=ActionType.RUN_COMMAND,
                target="echo hi",
                data={"command": "echo hi"},
                reason="test",
                agent_id="a",
            ),
            UserContext(
                user_id="u",
                allowed_actions={"RUN_COMMAND": ActionPermission(safe=False)},
            ),
        )

        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "hook_crash"
        assert "shield blew up" in result.reason
        assert result.decision_path == "hook_crash"
        assert result.dg_exception == "ValueError('shield blew up')"

    def test_permission_block_has_no_dg_exception(self) -> None:
        dg = make_deterministic_guardian()
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
        dg = make_deterministic_guardian()
        constraints = {"blocked_patterns": ["sudo"]}
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
            deterministic_guardian=make_deterministic_guardian(),
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


class TestCalendarConstraintEnforcement:
    def test_calendar_constraints_enforced_at_runtime(self) -> None:
        dg = make_deterministic_guardian()
        result = decide_dg_sync(
            dg,
            IntentFrame(
                action=ActionType.CREATE_EVENT,
                target="personal",
                data={"calendar": "personal"},
                reason="test",
                agent_id="a",
            ),
            UserContext(
                user_id="u",
                allowed_actions={
                    "CREATE_EVENT": ActionPermission(
                        safe=False,
                        constraints={"allowed_calendars": ["work"]},
                    ),
                },
            ),
        )

        assert result.decision is DeterministicDecision.BLOCK
        assert result.matched_gate == "constraint"

    def test_calendar_undecided_carries_constraint_context(self) -> None:
        dg = make_deterministic_guardian()
        result = decide_dg_sync(
            dg,
            IntentFrame(
                action=ActionType.CREATE_EVENT,
                target="work",
                data={"calendar": "work"},
                reason="test",
                agent_id="a",
            ),
            UserContext(
                user_id="u",
                allowed_actions={
                    "CREATE_EVENT": ActionPermission(
                        safe=False,
                        constraints={"allowed_calendars": ["work"]},
                    ),
                },
            ),
        )

        assert result.decision is DeterministicDecision.UNDECIDED
        assert result.bundle_ai_context is not None
        assert result.bundle_ai_context.constraint_context is not None
        assert "work" in result.bundle_ai_context.constraint_context.action_constraints
