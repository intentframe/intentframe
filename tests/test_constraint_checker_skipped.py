"""Runtime warning + audit when YAML constraints have no wired checker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from action_registry.types import ActionType
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicGuardian,
)
from intentframe_core.enums import Decision, RiskLevel, Reversibility
from intentframe_core.types import (
    AnalysisReport,
    ExecutionResult,
    IntentFrame,
    UserContext,
)
from intentframe_bundle_sdk.action import NullActionBundle
from intentframe_bundle_sdk.types import BundleContext
from policy_registry.constraints.calendar import CalendarConstraints
from policy_registry.models import ActionPermission
from tests.deterministic_accuracy._helpers import decide_dg_sync


def _calendar_permission(*, safe: bool = False) -> ActionPermission:
    return ActionPermission(
        safe=safe,
        constraints=CalendarConstraints(allowed_calendars=["work"]),
    )


class TestCheckPolicyMissingChecker:
    def test_records_skipped_on_bundle_context(self) -> None:
        bundle = NullActionBundle()
        ctx = BundleContext(
            intent=IntentFrame(
                action=ActionType.CREATE_EVENT,
                target="work",
                reason="test",
                agent_id="a",
            )
        )
        permission = _calendar_permission()
        outcome = bundle.check_policy(ctx.intent, permission, ctx, verbose=False)

        assert outcome.decision.value == "CONTINUE"
        assert ctx.constraint_checker_skipped == "CalendarConstraints"

    def test_dg_undecided_for_unmapped_constraint_action(self) -> None:
        dg = DeterministicGuardian()
        result = decide_dg_sync(
            dg,
            IntentFrame(
                action=ActionType.CREATE_EVENT,
                target="work",
                reason="test",
                agent_id="a",
            ),
            UserContext(
                user_id="u",
                allowed_actions={"CREATE_EVENT": _calendar_permission()},
            ),
        )

        assert result.decision is DeterministicDecision.UNDECIDED
        assert result.matched_gate == "undecided"
        assert result.bundle_context is not None
        assert result.bundle_context.constraint_checker_skipped == "CalendarConstraints"

    def test_audit_fields_include_constraint_checker_skipped(self) -> None:
        from intentframe_bundle_sdk.types import enrichment_audit_fields

        ctx = BundleContext(
            intent=IntentFrame(
                action=ActionType.CREATE_EVENT,
                target="work",
                reason="test",
                agent_id="a",
            )
        )
        ctx.constraint_checker_skipped = "CalendarConstraints"
        assert enrichment_audit_fields(ctx) == {
            "constraint_checker_skipped": "CalendarConstraints",
        }


class TestPipelineAuditMissingChecker:
    def test_allow_path_audit_includes_constraint_checker_skipped(self) -> None:
        from intentframe_core.types import ValidationResult
        from intentframe_server.pipeline import IntentFrameRuntime

        runtime = IntentFrameRuntime(
            analysis_engine=AsyncMock(),
            guardian=AsyncMock(),
            executor=MagicMock(
                execute=MagicMock(
                    return_value=ExecutionResult(success=True, data={"ok": True})
                )
            ),
            verbose=False,
        )
        runtime._resolve_user_context = MagicMock(side_effect=lambda uc: uc)

        async def _allow(*args, **kwargs):
            return ValidationResult(
                decision=Decision.ALLOW,
                intent=args[0],
                message="ok",
            )

        runtime.guardian.validate = AsyncMock(side_effect=_allow)

        intent = IntentFrame(
            action=ActionType.LIST_CALENDARS,
            target="",
            reason="test",
            agent_id="a",
        )
        user = UserContext(
            user_id="u",
            allowed_actions={"LIST_CALENDARS": _calendar_permission(safe=True)},
        )

        asyncio.run(runtime.process_intent(intent, user))

        entry = runtime.audit_log[-1]
        assert entry["constraint_checker_skipped"] == "CalendarConstraints"
        runtime.analysis_engine.analyze.assert_not_called()
