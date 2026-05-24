"""Pins global deterministic gate order."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from action_registry.types import ActionType, DomainType
from intentframe_native_bundles import ensure_bundles_registered
from intentframe_native_bundles.actions.files.bundle import FilesActionBundle
from intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle
from intentframe_bundle_sdk.registry import action_bundle_for, domain_bundle_for
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome
from intentframe_core.types import IntentFrame, UserContext
from policy_registry.models import ActionPermission


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_bundles_registered()


def test_domain_runs_before_passive_read_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Domain BLOCK must fire before SDK passive-read ALLOW short-circuit."""
    order: list[str] = []
    bundle = FilesActionBundle()
    domain_bundle = domain_bundle_for(DomainType.FINANCE)
    assert domain_bundle is not None

    original_enforce = domain_bundle.enforce

    def track_enforce(intent, domain_constraints):
        order.append("domain")
        ctx = BundleContext(intent=intent.model_copy(deep=True))
        return BundlePhaseOutcome.block(
            ctx,
            reason="Domain violation (finance): test",
            matched_gate="domain",
        )

    def track_allow(self, intent, action_permission, ctx):
        order.append("allow")
        return BundlePhaseOutcome.allow(
            ctx, reason="should not run", matched_gate="custom_allow"
        )

    monkeypatch.setattr(domain_bundle, "enforce", track_enforce)
    monkeypatch.setattr(FilesActionBundle, "allow_gates", track_allow)

    from action_registry.types import ACTION_DOMAINS

    monkeypatch.setitem(ACTION_DOMAINS, ActionType.READ_FILE, DomainType.FINANCE)

    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="order test",
        agent_id="test",
    )
    permission = ActionPermission(safe=True)
    user_context = UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": permission},
        domain_constraints={"finance": {"max_amount": 1.0}},
    )

    result = asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
        )
    )

    monkeypatch.setattr(domain_bundle, "enforce", original_enforce)

    assert result.decision == "BLOCK"
    assert result.matched_gate == "domain"
    assert order == ["domain"]


def test_passive_read_runs_before_allow_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK passive-read ALLOW must fire before plugin allow_gates."""
    order: list[str] = []
    bundle = FilesActionBundle()

    def track_allow(self, intent, action_permission, ctx):
        order.append("allow")
        return BundlePhaseOutcome.continue_(ctx)

    monkeypatch.setattr(FilesActionBundle, "allow_gates", track_allow)

    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
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

    assert result.decision == "ALLOW"
    assert result.matched_gate == "passive_read"
    assert order == []


def test_email_bundle_selected_for_reply() -> None:
    from intentframe_native_bundles.actions.email.bundle import EmailActionBundle

    bundle = action_bundle_for(ActionType.REPLY_EMAIL.value)
    assert isinstance(bundle, EmailActionBundle)
