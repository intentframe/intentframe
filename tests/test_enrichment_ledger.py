"""Host enrichment ledger — submitted intent snapshot and audit fields."""

from __future__ import annotations

import asyncio

import pytest

from action_registry.types import ActionType
from intentframe_action_bundle.bundles.register import ensure_bundles_registered
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import (
    BundleContext,
    BundlePhaseOutcome,
    enrichment_audit_fields,
    enrichment_changed,
    record_enrichment,
)
from intentframe_core.types import IntentFrame, UserContext
from policy_registry.models import ActionPermission


@pytest.fixture(autouse=True)
def _bundles() -> None:
    ensure_bundles_registered()


def test_enrichment_changed_detects_target_update() -> None:
    submitted = IntentFrame(
        action=ActionType.GET_EMAIL,
        target="msg-123",
        data={"rfc_message_id": "msg-123"},
        reason="test",
        agent_id="a",
    )
    effective = submitted.model_copy(update={"target": 'Email "Hi" from alice@example.com'})
    assert enrichment_changed(submitted, effective)
    assert not enrichment_changed(submitted, submitted)


def test_record_enrichment_populates_ledger() -> None:
    submitted = IntentFrame(
        action=ActionType.REPLY_EMAIL,
        target="id-1",
        data={"rfc_message_id": "id-1"},
        reason="test",
        agent_id="a",
    )
    ctx = BundleContext(intent=submitted.model_copy(deep=True))
    ctx.enriched_intent = submitted.model_copy(
        update={"target": 'Reply to "Subject" from bob@example.com', "data": {"to": "bob@example.com"}}
    )
    record_enrichment(ctx, bundle_id="email")
    assert ctx.enrichment is not None
    assert ctx.enrichment.applied is True
    assert ctx.enrichment.bundle_id == "email"
    assert ctx.enrichment.target_submitted == "id-1"
    assert "Subject" in ctx.enrichment.target_after

    audit = enrichment_audit_fields(ctx)
    assert audit["enrichment_applied"] is True
    assert audit["enrichment_bundle_id"] == "email"
    assert audit["target_submitted"] == "id-1"


def test_runner_evidence_then_enrich_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """prepare_evidence runs before enrich; ledger after enrich."""
    from intentframe_action_bundle.bundles.files import FilesActionBundle

    bundle = FilesActionBundle()
    order: list[str] = []
    submitted = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        data=None,
        reason="test",
        agent_id="a",
    )

    async def track_evidence(self, intent, permission, ctx, *, verbose=False):
        order.append("evidence")
        return BundlePhaseOutcome.continue_(ctx)

    async def track_enrich(self, intent, permission, ctx, *, verbose=False):
        order.append("enrich")
        ctx.enriched_intent = intent.model_copy(update={"target": "/tmp/x-enriched"})
        return BundlePhaseOutcome.continue_(ctx)

    monkeypatch.setattr(FilesActionBundle, "prepare_evidence", track_evidence)
    monkeypatch.setattr(FilesActionBundle, "enrich", track_enrich)

    user_context = UserContext(
        user_id="u",
        allowed_actions={"READ_FILE": ActionPermission(safe=True)},
    )
    asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            submitted,
            user_context.allowed_actions["READ_FILE"],
            user_context,
        )
    )
    assert order == ["evidence", "enrich"]


def test_enrich_must_not_return_terminal() -> None:
    from intentframe_action_bundle.bundles.files import FilesActionBundle

    bundle = FilesActionBundle()

    async def bad_enrich(self, intent, permission, ctx, *, verbose=False):
        return BundlePhaseOutcome.block(ctx, reason="nope", matched_gate="bad")

    bundle.enrich = bad_enrich.__get__(bundle, FilesActionBundle)

    user_context = UserContext(
        user_id="u",
        allowed_actions={"READ_FILE": ActionPermission(safe=True)},
    )
    with pytest.raises(RuntimeError, match="enrich\\(\\) returned terminal"):
        asyncio.run(
            DeterministicRunner.run_action_bundle(
                bundle,
                IntentFrame(
                    action=ActionType.READ_FILE,
                    target="/tmp/x",
                    data=None,
                    reason="test",
                    agent_id="a",
                ),
                user_context.allowed_actions["READ_FILE"],
                user_context,
            )
        )


def test_pipeline_audit_fields_empty_without_context() -> None:
    from intentframe_server.pipeline import IntentFrameRuntime

    assert IntentFrameRuntime._enrichment_audit_fields(None) == {}
