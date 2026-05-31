"""Executor must receive the actor-submitted intent, not enriched copies.

Regression guard for the runtime contract documented in
``IntentFrameRuntime._process_intent_impl`` and ``ValidationResult``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from action_registry.types import ActionType
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicResult,
)
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


def _submitted_reply_intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.REPLY_EMAIL,
        target="",
        reason="test reply",
        agent_id="test_agent",
        data={
            "rfc_message_id": "<msg@example.com>",
            "body": "Thanks!",
            "reply_all": False,
        },
    )


@pytest.mark.asyncio
async def test_executor_receives_submitted_intent_not_enriched() -> None:
    submitted = _submitted_reply_intent()
    enriched = submitted.model_copy(
        update={
            "target": 'Reply to "Invoice" from alice@example.com',
            "data": {
                **(submitted.data or {}),
                "to": "alice@example.com",
                "email_subject": "Invoice",
                "email_from": "alice@example.com",
            },
        }
    )
    ctx = BundleContext(intent=submitted.model_copy(deep=True))
    ctx.enriched_intent = enriched

    analysis_engine = AsyncMock()
    analysis_engine.analyze = AsyncMock(
        return_value=AnalysisReport(
            stated_intent="reply",
            risk_factors={"overall": RiskLevel.LOW},
            reversibility=Reversibility.FULLY_REVERSIBLE,
            confidence=1.0,
            recommendation="allow",
        )
    )

    guardian = AsyncMock()
    guardian.validate = AsyncMock(
        return_value=ValidationResult(
            decision=Decision.ALLOW,
            intent=enriched,
            message="Allowed",
        )
    )

    executor = MagicMock()
    executor.execute = MagicMock(
        return_value=ExecutionResult(success=True, data={"replied": True})
    )

    runtime = IntentFrameRuntime(
        analysis_engine=analysis_engine,
        guardian=guardian,
        executor=executor,
        verbose=False,
    )
    runtime._resolve_user_context = lambda uc: uc
    runtime.deterministic_guardian.decide_async = AsyncMock(
        return_value=DeterministicResult(
            decision=DeterministicDecision.UNDECIDED,
            bundle_context=ctx,
            bundle_ai_context=BundleAIContext(),
        )
    )

    user_context = UserContext(
        user_id="test",
        allowed_actions={"REPLY_EMAIL": ActionPermission(safe=False)},
    )

    result = await runtime.process_intent(submitted, user_context)

    assert result.success
    executor.execute.assert_called_once()
    executed = executor.execute.call_args[0][0]
    assert executed.target == submitted.target
    assert executed.data == submitted.data
    assert "to" not in (executed.data or {})
