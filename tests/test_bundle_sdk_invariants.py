"""SDK contract, runner, registry strictness, and substrate boundary invariants."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from action_registry.types import ActionType
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.registry import (
    all_action_bundles,
    all_domain_bundles,
    register_action_bundle,
)
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import (
    BundleContext,
    BundlePhaseOutcome,
)
from intentframe_components.guardian.deterministic import DeterministicGuardian
from intentframe_core.types import IntentFrame, UserContext
from intentframe_native_bundles.actions.files.bundle import FilesActionBundle
from intentframe_bundle_sdk.registry import domain_bundle_for
from policy_registry.models import ActionPermission as PolicyActionPermission
from tests._bundle_loader import ensure_test_bundles_loaded

_FORBIDDEN_IN_AIGUARDIAN = (
    "CONSTRAINT_CHECKERS",
    "action_bundle_for",
    "domain_bundle_for",
    "describe_constraints",
    "domain_bundle.describe",
    "summarize_constraints",
)


@pytest.fixture(autouse=True)
def _load_bundles() -> None:
    ensure_test_bundles_loaded()


def test_registry_rejects_duplicate_action_id() -> None:
    class First(ActionBundle):
        bundle_id = "first"
        action_ids = frozenset({"DUPE_ACTION_TEST"})

    class Second(ActionBundle):
        bundle_id = "second"
        action_ids = frozenset({"DUPE_ACTION_TEST"})

    register_action_bundle(First())
    with pytest.raises(ValueError, match="duplicate action_id"):
        register_action_bundle(Second())


def test_registry_rejects_empty_bundle_id() -> None:
    class Empty(ActionBundle):
        bundle_id = ""
        action_ids = frozenset({"X"})

    with pytest.raises(ValueError, match="bundle_id"):
        register_action_bundle(Empty())


def test_registry_rejects_empty_action_ids() -> None:
    class NoActions(ActionBundle):
        bundle_id = "no_actions"
        action_ids = frozenset()

    with pytest.raises(ValueError, match="action_ids"):
        register_action_bundle(NoActions())


def test_registry_rejects_passive_read_not_subset() -> None:
    class BadPassive(ActionBundle):
        bundle_id = "bad_passive"
        action_ids = frozenset({"A"})
        passive_read_action_ids = frozenset({"B"})

    with pytest.raises(ValueError, match="passive_read_action_ids"):
        register_action_bundle(BadPassive())


def test_bundle_hooks_never_accept_user_context() -> None:
    hook_names = (
        "startup",
        "prepare_evidence",
        "enrich",
        "validate_constraints",
        "enforce_constraints",
        "structural_gates",
        "allow_gates",
        "build_ai_context",
        "describe_constraints",
        "aclose",
    )
    for bundle in all_action_bundles():
        for name in hook_names:
            sig = inspect.signature(getattr(bundle, name))
            assert "user_context" not in sig.parameters, (
                f"{bundle.bundle_id}.{name} must not accept user_context"
            )
    for domain in all_domain_bundles():
        for name in ("startup", "validate", "enforce", "describe", "aclose"):
            sig = inspect.signature(getattr(domain, name))
            assert "user_context" not in sig.parameters, (
                f"{domain.domain_id}.{name} must not accept user_context"
            )


def test_no_enforcement_blocks_constrained_action_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoEnforceBundle(ActionBundle):
        bundle_id = "no_enforce_runtime"
        action_ids = frozenset({ActionType.READ_FILE.value})

    import intentframe_bundle_sdk.registry as bundle_registry

    original = bundle_registry._ACTION_BY_ID[ActionType.READ_FILE.value]
    monkeypatch.setitem(
        bundle_registry._ACTION_BY_ID,
        ActionType.READ_FILE.value,
        NoEnforceBundle(),
    )

    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="test",
        agent_id="test",
    )
    permission = PolicyActionPermission(
        safe=True,
        constraints={"allowed_paths": ["/tmp/*"]},
    )
    user_context = UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": permission},
    )
    result = asyncio.run(
        DeterministicRunner.run_action_bundle(
            NoEnforceBundle(),
            intent,
            permission,
            user_context,
        )
    )
    assert result.decision == "BLOCK"
    assert result.matched_gate == "no_enforcement"
    assert original.bundle_id == "files"


def test_deterministic_guardian_blocks_allowed_action_without_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import intentframe_bundle_sdk.registry as bundle_registry

    monkeypatch.delitem(bundle_registry._ACTION_BY_ID, ActionType.READ_FILE.value)
    dg = DeterministicGuardian(packages=["intentframe_native_bundles"])
    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="test",
        agent_id="test",
    )
    user_context = UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": PolicyActionPermission(safe=True)},
    )
    result = asyncio.run(dg.decide_async(intent, user_context))
    assert result.decision.value == "BLOCK"
    assert result.matched_gate == "no_bundle"


def test_mutation_safety_constraints_not_shared_with_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = FilesActionBundle()
    host_constraints = {"allowed_paths": ["/tmp/*"]}
    intent = IntentFrame(
        action=ActionType.WRITE_FILE,
        target="/tmp/out.txt",
        reason="mutation test",
        agent_id="test",
        data={"content": "x"},
    )
    user_context = UserContext(
        user_id="test",
        allowed_actions={
            "WRITE_FILE": PolicyActionPermission(
                safe=False,
                constraints=host_constraints.copy(),
            ),
        },
    )
    original_snapshot = dict(host_constraints)

    def _mutating_enforce(self, intent, action_permission, ctx, *, verbose=False):
        if action_permission.constraints is not None:
            action_permission.constraints["allowed_paths"] = ["/mutated"]
        return BundlePhaseOutcome.continue_(ctx)

    monkeypatch.setattr(FilesActionBundle, "enforce_constraints", _mutating_enforce)
    asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            PolicyActionPermission(safe=False, constraints=host_constraints.copy()),
            user_context,
        )
    )
    assert host_constraints == original_snapshot


def test_undecided_populates_constraint_context_and_calls_describe_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    bundle = FilesActionBundle()
    original = bundle.describe_constraints

    def counting_describe(action_permission):
        calls["count"] += 1
        return original(action_permission)

    monkeypatch.setattr(bundle, "describe_constraints", counting_describe)

    intent = IntentFrame(
        action=ActionType.WRITE_FILE,
        target="/tmp/out.txt",
        reason="prompt ctx",
        agent_id="test",
        data={"content": "x"},
    )
    permission = PolicyActionPermission(
        safe=False,
        constraints={"allowed_paths": ["/tmp/*"]},
    )
    user_context = UserContext(
        user_id="test",
        allowed_actions={"WRITE_FILE": permission},
    )

    result = asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
        )
    )
    assert result.decision == "UNDECIDED"
    assert result.bundle_ai_context is not None
    ctx = result.bundle_ai_context.constraint_context
    assert ctx is not None
    assert ctx.action_constraints
    assert calls["count"] == 1


def test_terminal_allow_has_no_constraint_context() -> None:
    bundle = FilesActionBundle()
    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="passive",
        agent_id="test",
    )
    permission = PolicyActionPermission(safe=True)
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
    assert result.bundle_ai_context is None


def test_block_has_no_constraint_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import intentframe_bundle_sdk.registry as bundle_registry

    domain_bundle = bundle_registry.domain_bundle_for("finance")
    assert domain_bundle is not None

    def block_enforce(intent, domain_constraints):
        ctx = BundleContext(intent=intent.model_copy(deep=True))
        return BundlePhaseOutcome.block(
            ctx,
            reason="blocked",
            matched_gate="domain",
        )

    monkeypatch.setattr(domain_bundle, "enforce", block_enforce)
    monkeypatch.setitem(
        bundle_registry._ACTION_TO_DOMAINS,
        ActionType.READ_FILE.value,
        ("finance",),
    )

    bundle = FilesActionBundle()
    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="block ctx",
        agent_id="test",
    )
    permission = PolicyActionPermission(safe=True)
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

    assert result.decision == "BLOCK"
    assert result.bundle_ai_context is None


def test_missing_describe_falls_back_to_str_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = FilesActionBundle()
    constraints = {"allowed_paths": ["/tmp/*"]}
    monkeypatch.setattr(bundle, "describe_constraints", lambda _perm: None)

    intent = IntentFrame(
        action=ActionType.WRITE_FILE,
        target="/tmp/out.txt",
        reason="fallback",
        agent_id="test",
        data={"content": "x"},
    )
    permission = PolicyActionPermission(safe=False, constraints=constraints)
    user_context = UserContext(
        user_id="test",
        allowed_actions={"WRITE_FILE": permission},
    )

    result = asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
        )
    )
    assert result.decision == "UNDECIDED"
    ctx = result.bundle_ai_context.constraint_context
    assert ctx is not None
    assert str(constraints) in ctx.action_constraints or "/tmp/*" in ctx.action_constraints


def test_routed_domain_constraints_rendered_on_undecided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = FilesActionBundle()
    import intentframe_bundle_sdk.registry as bundle_registry

    monkeypatch.setitem(
        bundle_registry._ACTION_TO_DOMAINS,
        ActionType.WRITE_FILE.value,
        ("finance",),
    )

    intent = IntentFrame(
        action=ActionType.WRITE_FILE,
        target="/tmp/out.txt",
        reason="domain prompt",
        agent_id="test",
        data={"content": "x"},
    )
    permission = PolicyActionPermission(
        safe=False,
        constraints={"allowed_paths": ["/tmp/*"]},
    )
    user_context = UserContext(
        user_id="test",
        allowed_actions={"WRITE_FILE": permission},
        domain_constraints={"finance": {"max_amount": 500.0}},
    )

    result = asyncio.run(
        DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
        )
    )
    assert result.decision == "UNDECIDED"
    ctx = result.bundle_ai_context.constraint_context
    assert ctx is not None
    assert ctx.domain_constraints
    assert "finance" in ctx.enforced_domains[0] or any(
        "max_amount" in line or "finance" in line for line in ctx.domain_constraints
    )


def test_structural_gates_before_passive_read_before_allow_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    bundle = FilesActionBundle()

    def track_structural(self, intent, ctx):
        order.append("structural")
        return BundlePhaseOutcome.continue_(ctx)

    def track_allow(self, intent, action_permission, ctx):
        order.append("allow")
        return BundlePhaseOutcome.continue_(ctx)

    monkeypatch.setattr(FilesActionBundle, "structural_gates", track_structural)
    monkeypatch.setattr(FilesActionBundle, "allow_gates", track_allow)

    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="order",
        agent_id="test",
    )
    permission = PolicyActionPermission(safe=True)
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
    assert order == ["structural"]


def test_bundle_phase_outcome_decision_path_passthrough() -> None:
    ctx = BundleContext(
        intent=IntentFrame(
            action=ActionType.READ_FILE,
            target="/tmp",
            reason="x",
            agent_id="a",
        )
    )
    blocked = BundlePhaseOutcome.block(
        ctx, reason="nope", matched_gate="command_shield"
    )
    assert blocked.to_deterministic_result().decision_path == "command_shield"

    allowed = BundlePhaseOutcome.allow(ctx, reason="ok", matched_gate="")
    assert allowed.to_deterministic_result().decision_path == "deterministic"


def test_aiguardian_source_has_no_plugin_registry_coupling() -> None:
    source = Path("intentframe_components/guardian/engine.py").read_text(encoding="utf-8")
    for token in _FORBIDDEN_IN_AIGUARDIAN:
        assert token not in source, f"AIGuardian must not reference {token!r}"
