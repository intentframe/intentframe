"""Pins global deterministic gate order (legacy 66e567c step 2.5)."""

from __future__ import annotations

import asyncio

import pytest

from action_registry.types import ActionType
from intentframe_action_bundle.bundles.register import ensure_bundles_registered
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import BundleDeterministicResult, BundlePhaseOutcome
from intentframe_core.types import IntentFrame, UserContext
from policy_registry.constraints.email import EmailConstraints
from policy_registry.models import ActionPermission


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_bundles_registered()


def test_domain_runs_before_allow_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Domain BLOCK must fire before passive-read ALLOW short-circuit."""
    order: list[str] = []
    from intentframe_action_bundle.bundles.passive_read import PassiveReadActionBundle

    bundle = PassiveReadActionBundle()

    from intentframe_bundle_sdk import runner as runner_mod

    def fake_domain(intent, user_context, ctx):
        order.append("domain")
        return BundleDeterministicResult(
            decision="BLOCK",
            context=ctx,
            reason="Domain violation (deletion): test",
            matched_gate="domain",
        )

    def track_allow(self, intent, permission, ctx):
        order.append("allow")
        return BundlePhaseOutcome.allow(
            ctx, reason="should not run", matched_gate="passive_read"
        )

    monkeypatch.setattr(
        runner_mod.DeterministicRunner,
        "_run_domain",
        staticmethod(fake_domain),
    )
    monkeypatch.setattr(PassiveReadActionBundle, "allow_gates", track_allow)

    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        data=None,
        reason="order test",
        agent_id="test",
    )
    permission = ActionPermission(safe=True)
    user_context = UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": permission},
    )

    result = asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
        )
    )

    assert result.decision == "BLOCK"
    assert result.matched_gate == "domain"
    assert order == ["domain"]


def test_email_bundle_selected_for_reply() -> None:
    from intentframe_action_bundle.bundles.email import EmailActionBundle

    bundle = action_bundle_for(
        ActionType.REPLY_EMAIL.value,
        ActionPermission(safe=False, constraints=EmailConstraints()),
    )
    assert isinstance(bundle, EmailActionBundle)
