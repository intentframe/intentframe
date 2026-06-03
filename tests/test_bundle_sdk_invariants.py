"""SDK contract, runner, registry strictness, and substrate boundary invariants."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from intentframe_native_kit.action_registry.types import ActionType
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
from intentframe_native_kit.intentframe_native_bundles.actions.files.bundle import FilesActionBundle
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
    dg = DeterministicGuardian(packages=["intentframe_native_kit.intentframe_native_bundles"])
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

    async def _mutating_enforce(self, intent, action_permission, ctx, *, verbose=False):
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

    async def counting_describe(action_permission):
        calls["count"] += 1
        return await original(action_permission)

    monkeypatch.setattr(bundle, "describe_constraints", counting_describe)

    intent = IntentFrame(
        action=ActionType.WRITE_FILE,
        target="/tmp/out.txt",
        reason="prompt ctx",
        agent_id="test",
        data={"path": "/tmp/out.txt", "content": "x"},
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


def test_domain_schema_blocks_missing_finance_data() -> None:
    bundle = FilesActionBundle()
    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/x",
        reason="finance shape",
        agent_id="test",
    )
    permission = PolicyActionPermission(safe=True)
    user_context = UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": permission},
        domain_constraints={"finance": {"max_amount": 1.0}},
    )

    import intentframe_bundle_sdk.registry as bundle_registry

    previous = bundle_registry._ACTION_TO_DOMAINS.get(ActionType.READ_FILE.value)
    bundle_registry._ACTION_TO_DOMAINS[ActionType.READ_FILE.value] = ("finance",)
    try:
        result = asyncio.run(
            DeterministicRunner.run_action_bundle(
                bundle,
                intent,
                permission,
                user_context,
            )
        )
    finally:
        if previous is None:
            bundle_registry._ACTION_TO_DOMAINS.pop(ActionType.READ_FILE.value, None)
        else:
            bundle_registry._ACTION_TO_DOMAINS[ActionType.READ_FILE.value] = previous

    assert result.decision == "BLOCK"
    assert result.matched_gate == "domain_schema"
    assert "invalid intent shape" in result.reason
    assert result.bundle_ai_context is None


def test_domain_schema_blocks_deletion_when_path_only_in_target() -> None:
    # ``path`` must be in IntentFrame.data (the executable contract). A path
    # carried only in ``target`` (display/audit) does not satisfy the deletion
    # schema and must BLOCK at the domain_schema gate.
    bundle = FilesActionBundle()
    intent = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/x",
        reason="deletion shape",
        agent_id="test",
    )
    permission = PolicyActionPermission(safe=False)
    user_context = UserContext(
        user_id="test",
        allowed_actions={"DELETE_FILE": permission},
        domain_constraints={"deletion": {"allowed_paths": ["/tmp/*"]}},
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
    assert result.matched_gate == "domain_schema"
    assert "invalid intent shape" in result.reason
    assert result.bundle_ai_context is None


def test_finance_domain_blocks_missing_amount_for_max_amount_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle

    bundle = FinanceDomainBundle()
    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="invoice",
        reason="finance policy",
        agent_id="test",
        data={"currency": "USD", "recipient": "ACME Corp"},
    )
    outcome = bundle.enforce(intent, {"max_amount": 5000.0})
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "domain"
    assert "amount" in (outcome.reason or "").lower()


def test_finance_domain_blocks_missing_recipient_for_allowlist_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle

    bundle = FinanceDomainBundle()
    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="invoice",
        reason="finance policy",
        agent_id="test",
        data={"amount": 100.0, "currency": "USD"},
    )
    outcome = bundle.enforce(
        intent,
        {"allowed_recipients": ["ACME Corp", "Office Depot"]},
    )
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "domain"
    assert "recipient" in (outcome.reason or "").lower()


def test_api_bundle_blocks_missing_amount_for_max_amount_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.api.bundle import ApiActionBundle

    bundle = ApiActionBundle()
    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="invoice",
        reason="api policy",
        agent_id="test",
        data={"url": "https://api.example.com/pay"},
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"max_amount": 5000.0},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "constraint"
    assert "amount" in (outcome.reason or "").lower()


def test_api_bundle_blocks_missing_url_for_allowed_endpoints_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.api.bundle import ApiActionBundle

    bundle = ApiActionBundle()
    intent = IntentFrame(
        action=ActionType.HTTP_GET,
        target="https://api.example.com/status",
        reason="api policy",
        agent_id="test",
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_endpoints": ["https://api.example.com/*"]},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "constraint"
    assert "url" in (outcome.reason or "").lower()


def test_calendar_bundle_blocks_missing_calendar_for_allowed_calendars_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.calendar.bundle import CalendarActionBundle

    bundle = CalendarActionBundle()
    intent = IntentFrame(
        action=ActionType.CREATE_EVENT,
        target="work",
        reason="calendar policy",
        agent_id="test",
        data={"title": "Standup"},
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_calendars": ["work", "personal"]},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "constraint"
    assert "calendar" in (outcome.reason or "").lower()


def test_terminal_bundle_blocks_missing_command_when_policy_needs_command() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle

    bundle = TerminalActionBundle()
    intent = IntentFrame(
        action=ActionType.RUN_COMMAND,
        target="ls -la",
        reason="terminal policy",
        agent_id="test",
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_commands": ["ls *"]},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "constraint"
    assert "command" in (outcome.reason or "").lower()


def test_deletion_domain_blocks_missing_path_for_allowed_paths_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.domains.deletion.bundle import DeletionDomainBundle

    bundle = DeletionDomainBundle()
    intent = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/x",
        reason="deletion policy",
        agent_id="test",
        data={"irreversible": False},
    )
    outcome = bundle.enforce(intent, {"allowed_paths": ["/tmp/*"]})
    assert outcome.decision == "BLOCK"
    assert outcome.matched_gate == "domain"
    assert "path" in (outcome.reason or "").lower()


def test_domain_schemas_ignore_unrelated_fields_for_slice_validation() -> None:
    from intentframe_native_kit.action_registry.domains.deletion import DeletionIntentData
    from intentframe_native_kit.action_registry.domains.finance import FinancialIntentData

    combined = {
        "amount": 250.0,
        "currency": "USD",
        "recipient": "ACME Corp",
        "path": "/tmp/invoice.pdf",
        "irreversible": False,
        "rfc_message_id": "<extra@example.com>",
    }

    finance = FinancialIntentData.validate_slice(combined)
    deletion = DeletionIntentData.validate_slice(combined)

    assert finance.amount == 250.0
    assert finance.recipient == "ACME Corp"
    assert deletion.path == "/tmp/invoice.pdf"
    assert deletion.irreversible is False


def test_domain_shape_checks_compose_for_many_to_many_routing() -> None:
    from intentframe_bundle_sdk.domain import check_domain_intent_shape
    from intentframe_native_kit.intentframe_native_bundles.domains.deletion.bundle import DeletionDomainBundle
    from intentframe_native_kit.intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle

    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="invoice",
        reason="multi-domain slice",
        agent_id="test",
        data={
            "amount": 250.0,
            "currency": "USD",
            "recipient": "ACME Corp",
            "path": "/tmp/invoice.pdf",
            "irreversible": False,
        },
    )

    finance_shape = check_domain_intent_shape(FinanceDomainBundle(), intent)
    deletion_shape = check_domain_intent_shape(DeletionDomainBundle(), intent)

    assert finance_shape.terminal is False
    assert deletion_shape.terminal is False


def test_runner_applies_all_routed_domain_slices() -> None:
    import intentframe_bundle_sdk.registry as bundle_registry

    bundle = FilesActionBundle()
    intent = IntentFrame(
        action=ActionType.READ_FILE,
        target="/tmp/invoice.pdf",
        reason="many-to-many domains",
        agent_id="test",
        data={
            "path": "/tmp/invoice.pdf",
            "amount": 250.0,
            "currency": "USD",
            "recipient": "ACME Corp",
            "irreversible": False,
        },
    )
    permission = PolicyActionPermission(safe=True)
    user_context = UserContext(
        user_id="test",
        allowed_actions={"READ_FILE": permission},
        domain_constraints={
            "finance": {"max_amount": 5000.0},
            "deletion": {"allowed_paths": ["/tmp/*"]},
        },
    )

    previous = bundle_registry._ACTION_TO_DOMAINS.get(ActionType.READ_FILE.value)
    bundle_registry._ACTION_TO_DOMAINS[ActionType.READ_FILE.value] = (
        "deletion",
        "finance",
    )
    try:
        result = asyncio.run(
            DeterministicRunner.run_action_bundle(
                bundle,
                intent,
                permission,
                user_context,
            )
        )
    finally:
        if previous is None:
            bundle_registry._ACTION_TO_DOMAINS.pop(ActionType.READ_FILE.value, None)
        else:
            bundle_registry._ACTION_TO_DOMAINS[ActionType.READ_FILE.value] = previous

    assert result.decision != "BLOCK"


def test_missing_describe_falls_back_to_str_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = FilesActionBundle()
    constraints = {"allowed_paths": ["/tmp/*"]}
    async def _null_describe(_perm):
        return None

    monkeypatch.setattr(bundle, "describe_constraints", _null_describe)

    intent = IntentFrame(
        action=ActionType.WRITE_FILE,
        target="/tmp/out.txt",
        reason="fallback",
        agent_id="test",
        data={"path": "/tmp/out.txt", "content": "x"},
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
        data={"path": "/tmp/out.txt", "amount": 100.0, "content": "x"},
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

    async def track_structural(self, intent, ctx, **_kw):
        order.append("structural")
        return BundlePhaseOutcome.continue_(ctx)

    async def track_allow(self, intent, action_permission, ctx, **_kw):
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


def test_terminal_pre_pipeline_ignores_command_only_in_target() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.terminal.pre_pipeline import (
        run_terminal_pre_pipeline,
    )

    intent = IntentFrame(
        action=ActionType.RUN_COMMAND,
        target="sudo rm -rf /",
        reason="target-only command must not run shield",
        agent_id="test",
    )
    intel, signals, early_block, audit = run_terminal_pre_pipeline(intent)
    assert intel is None
    assert signals == ()
    assert early_block is None
    assert audit is None


def test_browser_bundle_blocks_url_only_in_target() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.browser.bundle import BrowserActionBundle

    bundle = BrowserActionBundle()
    intent = IntentFrame(
        action=ActionType.OPEN_URL,
        target="https://example.com",
        reason="browser constraint",
        agent_id="test",
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_urls": ["https://example.com/*"]},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert "URL is required" in (outcome.reason or "")


def test_message_bundle_send_does_not_fall_back_to_target_for_contact_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.message.bundle import MessageActionBundle

    bundle = MessageActionBundle()
    intent = IntentFrame(
        action=ActionType.SEND_MESSAGE,
        target="+15551234567",
        reason="message constraint",
        agent_id="test",
        data={"text": "hi"},
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_contacts": ["+15551234567"]},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert "'to'" in (outcome.reason or "")


def test_message_bundle_read_uses_contact_field_for_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.message.bundle import MessageActionBundle

    bundle = MessageActionBundle()
    intent = IntentFrame(
        action=ActionType.READ_MESSAGES,
        target="Alice",
        reason="message constraint",
        agent_id="test",
        data={"contact": "alice@example.com", "limit": 5},
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_contacts": ["alice@example.com"]},
            ),
            ctx,
        )
    )
    assert outcome.decision != "BLOCK"


def test_message_bundle_read_blocks_unfiltered_read_under_contact_policy() -> None:
    from intentframe_native_kit.intentframe_native_bundles.actions.message.bundle import MessageActionBundle

    bundle = MessageActionBundle()
    intent = IntentFrame(
        action=ActionType.READ_MESSAGES,
        target="",
        reason="read all",
        agent_id="test",
        data={"limit": 5},
    )
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    outcome = asyncio.run(
        bundle.enforce_constraints(
            intent,
            PolicyActionPermission(
                safe=False,
                constraints={"allowed_contacts": ["alice@example.com"]},
            ),
            ctx,
        )
    )
    assert outcome.decision == "BLOCK"
    assert "'contact'" in (outcome.reason or "")


def test_aiguardian_source_has_no_plugin_registry_coupling() -> None:
    import intentframe_components.guardian.engine as _aiguardian_engine

    source = Path(_aiguardian_engine.__file__).read_text(encoding="utf-8")
    for token in _FORBIDDEN_IN_AIGUARDIAN:
        assert token not in source, f"AIGuardian must not reference {token!r}"
