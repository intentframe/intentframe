"""
Test Domain Hardening — typed schemas, domain modules, serialization, and pipeline integration.

Tests four layers:
  1. Domain modules directly (no AI, no server)
  2. Actor schema validation (no server)
  3. Serialization round-trip (no server)
  4. Full Guardian pipeline with domain modules + AI (requires OPENAI_API_KEY)

Run:
    .venv/bin/python demo/tests/test_domain_hardening.py          # all tests
    .venv/bin/python demo/tests/test_domain_hardening.py --no-ai  # skip AI tests
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from intentframe_native_kit.action_registry import ActionType
from intentframe_native_kit.action_registry.types import DomainType, ACTION_DOMAINS
from intentframe_core.types import IntentFrame
from intentframe_native_kit.action_registry.domains import DOMAIN_SCHEMAS
from policy_registry.models import UserPolicy
from intentframe_native_kit.intentframe_native_bundles.domains.deletion.bundle import DeletionDomainBundle
from intentframe_native_kit.intentframe_native_bundles.domains.deletion.constraints import DeletionConstraints
from intentframe_native_kit.intentframe_native_bundles.domain_routes import DOMAIN_ROUTES
from intentframe_native_kit.intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle
from intentframe_native_kit.intentframe_native_bundles.domains.finance.constraints import FinanceConstraints
from intentframe_bundle_sdk.types import PhaseDecision

passed_count = 0
failed_count = 0

_finance_domain = FinanceDomainBundle()
_deletion_domain = DeletionDomainBundle()


def _domain_slice(constraints) -> dict | None:
    if constraints is None:
        return None
    if isinstance(constraints, dict):
        return constraints
    if hasattr(constraints, "model_dump"):
        return constraints.model_dump(mode="python")
    return None


def _check_finance(intent: IntentFrame, constraints) -> tuple[bool, str]:
    outcome = _finance_domain.enforce(intent, _domain_slice(constraints))
    if outcome.decision is PhaseDecision.BLOCK:
        return False, outcome.reason or ""
    return True, ""


def _check_deletion(intent: IntentFrame, constraints) -> tuple[bool, str]:
    outcome = _deletion_domain.enforce(intent, _domain_slice(constraints))
    if outcome.decision is PhaseDecision.BLOCK:
        return False, outcome.reason or ""
    return True, ""


def check(label: str, condition: bool, detail: str = ""):
    global passed_count, failed_count
    if condition:
        passed_count += 1
        print(f"  PASS  {label}")
    else:
        failed_count += 1
        msg = f" -- {detail}" if detail else ""
        print(f"  FAIL  {label}{msg}")


# ═══════════════════════════════════════════════════════════════════
# 1. Domain Modules — direct structural checks (no AI, no server)
# ═══════════════════════════════════════════════════════════════════

def test_finance_module():
    print("\n" + "=" * 60)
    print("  1a. Finance Module — structural enforcement")
    print("=" * 60)

    module = _finance_domain
    constraints = FinanceConstraints(
        max_amount=5000.0,
        allowed_currencies=["USD", "EUR"],
        allowed_recipients=["ACME Corp", "Office Depot"],
    )

    # Amount exceeds limit → BLOCK
    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="acme_invoice",
        data={"amount": 8000.0, "currency": "USD", "recipient": "ACME Corp"},
    )
    ok, reason = _check_finance(intent, constraints)
    check("Amount $8k > $5k limit → BLOCK", not ok)
    check("  reason mentions limit", "exceeds" in reason.lower())

    # Amount within limit → pass (structurally valid)
    intent2 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="acme_invoice",
        data={"amount": 3000.0, "currency": "USD", "recipient": "ACME Corp"},
    )
    ok2, _ = _check_finance(intent2, constraints)
    check("Amount $3k < $5k limit → pass", ok2)

    # Wrong currency → BLOCK
    intent3 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="crypto_vendor",
        data={"amount": 100.0, "currency": "BTC"},
    )
    ok3, reason3 = _check_finance(intent3, constraints)
    check("Currency BTC not in [USD, EUR] → BLOCK", not ok3)
    check("  reason mentions currency", "currency" in reason3.lower())

    # Wrong recipient → BLOCK
    intent4 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="shady_vendor",
        data={"amount": 100.0, "currency": "USD", "recipient": "Unknown LLC"},
    )
    ok4, reason4 = _check_finance(intent4, constraints)
    check("Recipient 'Unknown LLC' not in allowlist → BLOCK", not ok4)

    # No recipient specified → BLOCK when allowed_recipients policy is configured
    intent5 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="vendor",
        data={"amount": 100.0, "currency": "USD"},
    )
    ok5, reason5 = _check_finance(intent5, constraints)
    check("No recipient with allowed_recipients policy → BLOCK", not ok5)
    check("  reason mentions recipient", "recipient" in reason5.lower())

    # Missing amount with max_amount policy → BLOCK
    intent5b = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="vendor",
        data={"currency": "USD", "recipient": "ACME Corp"},
    )
    ok5b, reason5b = _check_finance(intent5b, constraints)
    check("Missing amount with max_amount policy → BLOCK", not ok5b)
    check("  reason mentions amount", "amount" in reason5b.lower())

    # No domain constraints → pass (nothing to enforce)
    ok6, _ = _check_finance(intent, None)
    check("None domain constraints → pass", ok6)


def test_deletion_module():
    print("\n" + "=" * 60)
    print("  1b. Deletion Module — structural enforcement")
    print("=" * 60)

    module = _deletion_domain
    constraints = DeletionConstraints(
        allowed_paths=["/tmp/*", "/cache/"],
        block_irreversible=True,
    )

    # Path not in allowed list → BLOCK
    intent = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/important/database.db",
        data={"path": "/important/database.db", "irreversible": False},
    )
    ok, reason = _check_deletion(intent, constraints)
    check("Path /important/database.db not in [/tmp/*, /cache/] → BLOCK", not ok)
    check("  reason mentions path", "path" in reason.lower())

    # Path matches glob → check passes path, but irreversible → BLOCK
    intent2 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/scratch.log",
        data={"path": "/tmp/scratch.log", "irreversible": True},
    )
    ok2, reason2 = _check_deletion(intent2, constraints)
    check("Path /tmp/scratch.log matches, but irreversible=True → BLOCK", not ok2)
    check("  reason mentions irreversible", "irreversible" in reason2.lower())

    # Path matches, reversible → pass
    intent3 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/scratch.log",
        data={"path": "/tmp/scratch.log", "irreversible": False},
    )
    ok3, _ = _check_deletion(intent3, constraints)
    check("Path matches, irreversible=False → pass", ok3)

    # Path with prefix match → pass
    intent4 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/cache/old_data.bin",
        data={"path": "/cache/old_data.bin", "irreversible": False},
    )
    ok4, _ = _check_deletion(intent4, constraints)
    check("Path /cache/old_data.bin prefix matches /cache/ → pass", ok4)

    # Missing path with allowed_paths policy → BLOCK
    intent4b = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/scratch.log",
        data={"irreversible": False},
    )
    ok4b, reason4b = _check_deletion(intent4b, constraints)
    check("Missing path with allowed_paths policy → BLOCK", not ok4b)
    check("  reason mentions path", "path" in reason4b.lower())

    # No allowed_paths constraint → only check irreversible
    constraints2 = DeletionConstraints(block_irreversible=False)
    intent5 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/anywhere/file.txt",
        data={"path": "/anywhere/file.txt", "irreversible": True},
    )
    ok5, _ = _check_deletion(intent5, constraints2)
    check("No path restriction, block_irreversible=False → pass", ok5)


def test_deletion_module_host_file():
    """DELETE_HOST_FILE interactions with the shared DeletionConstraints.

    ``UserPolicy.domain_constraints`` is keyed by ``DomainType``, so a
    single ``DeletionConstraints`` instance is shared across every
    ``DELETE_*`` action a user is granted.  ``DeletionModule`` matches
    ``data["path"]`` with raw string / fnmatch — it is
    *vocabulary-blind* (no normalize_virtual_path, no canonicalize_real_path).
    The plan calls out that mixing virtual (``/home/*``) and real
    (``~/Documents/*``) patterns is unsafe unless the namespaces are
    disjoint by coincidence; the recommended configuration is
    ``allowed_paths=None`` when ``DELETE_HOST_FILE`` is granted, so the
    per-action ``HostFileConstraints`` + the DG ``delete_host_file_floor``
    gate carry the path-vocabulary load.

    These checks pin that the module behaves as the docstring describes
    so future changes (e.g. splitting ``DomainType.DELETION`` by
    category) intentionally break this test rather than silently change
    the contract.
    """
    print("\n" + "=" * 60)
    print("  1c. Deletion Module — DELETE_HOST_FILE interactions")
    print("=" * 60)

    module = _deletion_domain

    # Recommended config: allowed_paths=None → per-action HostFileConstraints
    # owns the path wall; module only enforces irreversible / confirmation.
    constraints_none = DeletionConstraints(
        allowed_paths=None,
        block_irreversible=False,
    )
    intent = IntentFrame(
        action=ActionType.DELETE_HOST_FILE,
        target="~/Documents/notes.md",
        data={"path": "~/Documents/notes.md", "irreversible": True},
    )
    ok, _ = _check_deletion(intent, constraints_none)
    check(
        "DELETE_HOST_FILE with allowed_paths=None → module passes (defers to per-action)",
        ok,
    )

    # block_irreversible still applies to DELETE_HOST_FILE — it's the one
    # path-agnostic setting that remains meaningful across vocabularies.
    constraints_block = DeletionConstraints(
        allowed_paths=None,
        block_irreversible=True,
    )
    ok_blocked, reason_blocked = _check_deletion(intent, constraints_block)
    check(
        "DELETE_HOST_FILE with block_irreversible=True → BLOCK",
        not ok_blocked,
    )
    check(
        "  reason mentions irreversible",
        "irreversible" in reason_blocked.lower(),
    )

    # Vocabulary warning in action: a virtual-path allowlist applied to a
    # real-path target deterministically fails (no coincidence).  Pins
    # the recommendation in the DeletionConstraints docstring — mixing
    # vocabularies is a foot-gun, not a feature.
    constraints_virtual = DeletionConstraints(
        allowed_paths=["/home/*"],
        block_irreversible=False,
    )
    intent_real = IntentFrame(
        action=ActionType.DELETE_HOST_FILE,
        target="~/Documents/notes.md",
        data={"path": "~/Documents/notes.md", "irreversible": False},
    )
    ok_cross, _ = _check_deletion(intent_real, constraints_virtual)
    check(
        "Virtual-path allowlist does NOT admit real-path DELETE_HOST_FILE target",
        not ok_cross,
    )


# ═══════════════════════════════════════════════════════════════════
# 2. Actor Schema Validation (no server)
# ═══════════════════════════════════════════════════════════════════

def test_actor_is_thin_transport():
    print("\n" + "=" * 60)
    print("  2. Actor is a thin transport — _build_intent")
    print("=" * 60)

    # Contract: the actor does NOT validate action taxonomy or domain intent
    # shape. ``IntentFrame.action`` is an opaque string and the actor passes
    # ``data`` through untouched. Domain shape is enforced server-side by the
    # bundle runner (``check_domain_intent_shape``) and domain bundles; unknown
    # actions fail closed at executor dispatch.
    from intentframe_actor import Actor
    actor = Actor(agent_id="test", user_id="test")

    # PAY_INVOICE with valid data → builds OK, action is the plain string.
    intent = actor._build_intent({
        "action": "PAY_INVOICE",
        "target": "vendor_invoice",
        "reason": "test",
        "data": {"amount": 5000.0, "currency": "USD"},
    })
    check("PAY_INVOICE with amount+currency → builds OK", intent is not None)
    check("  action is the plain string 'PAY_INVOICE'", intent.action == "PAY_INVOICE")
    check("  action equals ActionType.PAY_INVOICE.value", intent.action == ActionType.PAY_INVOICE.value)

    # PAY_INVOICE missing amount → actor no longer validates; still builds.
    intent_bad_finance = actor._build_intent({
        "action": "PAY_INVOICE",
        "target": "vendor",
        "reason": "test",
        "data": {"description": "no amount field"},
    })
    check(
        "PAY_INVOICE without amount → builds OK (validated server-side)",
        intent_bad_finance is not None,
    )

    # DELETE_FILE with valid data → builds OK.
    intent2 = actor._build_intent({
        "action": "DELETE_FILE",
        "target": "/tmp/file.txt",
        "reason": "cleanup",
        "data": {"path": "/tmp/file.txt"},
    })
    check("DELETE_FILE with path → builds OK", intent2 is not None)

    # DELETE_FILE missing path → actor no longer validates; still builds.
    intent_bad_deletion = actor._build_intent({
        "action": "DELETE_FILE",
        "target": "/tmp/file.txt",
        "reason": "cleanup",
        "data": {"filename": "file.txt"},
    })
    check(
        "DELETE_FILE without path → builds OK (validated server-side)",
        intent_bad_deletion is not None,
    )

    # Unknown action string → actor does not police the taxonomy.
    intent_unknown = actor._build_intent({
        "action": "NOT_A_REAL_ACTION",
        "target": "x",
        "reason": "author's responsibility",
    })
    check(
        "Unknown action string → builds OK (fails closed at dispatch)",
        intent_unknown is not None and intent_unknown.action == "NOT_A_REAL_ACTION",
    )

    # Non-critical-domain action → builds OK.
    intent3 = actor._build_intent({
        "action": "READ_FILE",
        "target": "/invoices/test.md",
        "reason": "reading",
    })
    check("READ_FILE → builds OK", intent3 is not None)


# ═══════════════════════════════════════════════════════════════════
# 3. Serialization Round-Trip (no server)
# ═══════════════════════════════════════════════════════════════════

def test_serialization_roundtrip():
    print("\n" + "=" * 60)
    print("  3. Serialization Round-Trip — JSON discriminated union")
    print("=" * 60)

    finance_constraints = FinanceConstraints(
        max_amount=5000.0,
        allowed_currencies=["USD", "EUR"],
        allowed_recipients=["ACME Corp"],
    )
    deletion_constraints = DeletionConstraints(
        require_confirmation=True,
        block_irreversible=True,
        allowed_paths=["/tmp/*"],
    )
    policy = UserPolicy(
        user_id="test_user",
        agent_id="domain-hardening-test",
        domain_constraints={
            "finance": finance_constraints.model_dump(mode="python"),
            "deletion": deletion_constraints.model_dump(mode="python"),
        },
    )

    json_str = policy.model_dump_json()
    restored = UserPolicy.model_validate_json(json_str)

    fc_raw = restored.domain_constraints.get("finance")
    dc_raw = restored.domain_constraints.get("deletion")

    check("Finance constraints survive round-trip", fc_raw is not None)
    fc = FinanceConstraints.model_validate(fc_raw) if fc_raw is not None else None
    check("  isinstance FinanceConstraints", isinstance(fc, FinanceConstraints))
    if isinstance(fc, FinanceConstraints):
        check("  max_amount preserved", fc.max_amount == 5000.0)
        check("  allowed_currencies preserved", fc.allowed_currencies == ["USD", "EUR"])
        check("  allowed_recipients preserved", fc.allowed_recipients == ["ACME Corp"])

    check("Deletion constraints survive round-trip", dc_raw is not None)
    dc = DeletionConstraints.model_validate(dc_raw) if dc_raw is not None else None
    check("  isinstance DeletionConstraints", isinstance(dc, DeletionConstraints))
    if isinstance(dc, DeletionConstraints):
        check("  require_confirmation preserved", dc.require_confirmation is True)
        check("  block_irreversible preserved", dc.block_irreversible is True)
        check("  allowed_paths preserved", dc.allowed_paths == ["/tmp/*"])

    # Verify domain modules work with deserialized constraints
    module = _finance_domain
    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="test",
        data={"amount": 8000.0, "currency": "USD"},
    )
    ok, reason = _check_finance(intent, fc_raw)
    check("Finance module works with deserialized constraints", not ok)
    check("  blocks $8k against $5k limit", "exceeds" in reason.lower())


# ═══════════════════════════════════════════════════════════════════
# 4. Taxonomy — domain routes, ACTION_DOMAINS hints, DOMAIN_SCHEMAS
# ═══════════════════════════════════════════════════════════════════

def test_taxonomy():
    print("\n" + "=" * 60)
    print("  4. Taxonomy — domain routes, ACTION_DOMAINS, DOMAIN_SCHEMAS")
    print("=" * 60)

    check("PAY_INVOICE in finance domain routes", "PAY_INVOICE" in DOMAIN_ROUTES["finance"])
    check("DELETE_FILE in deletion domain routes", "DELETE_FILE" in DOMAIN_ROUTES["deletion"])
    check(
        "DELETE_HOST_FILE mapped to DELETION",
        ACTION_DOMAINS.get(ActionType.DELETE_HOST_FILE) == DomainType.DELETION,
    )
    check("READ_FILE not in ACTION_DOMAINS", ActionType.READ_FILE not in ACTION_DOMAINS)
    check(
        "READ_HOST_FILE not in ACTION_DOMAINS",
        ActionType.READ_HOST_FILE not in ACTION_DOMAINS,
    )

    check("FINANCE has a schema", DomainType.FINANCE in DOMAIN_SCHEMAS)
    check("DELETION has a schema", DomainType.DELETION in DOMAIN_SCHEMAS)

    for domain_type in ACTION_DOMAINS.values():
        check(f"  {domain_type.value} domain has matching schema", domain_type in DOMAIN_SCHEMAS)


# ═══════════════════════════════════════════════════════════════════
# 5. Full Guardian Pipeline with AI (requires OPENAI_API_KEY)
# ═══════════════════════════════════════════════════════════════════

def test_guardian_pipeline():
    print("\n" + "=" * 60)
    print("  5. Full Guardian Pipeline — domain modules + AI")
    print("     (requires OPENAI_API_KEY)")
    print("=" * 60)

    if not os.environ.get("OPENAI_API_KEY"):
        print("\n  SKIPPED — OPENAI_API_KEY not set")
        print("  Set it to run AI pipeline tests.")
        return

    import asyncio
    from intentframe_core import UserContext
    from intentframe_components.analysis import AIAnalysisEngine
    from intentframe_components.guardian import AIGuardian
    from policy_registry.models import ActionPermission
    from intentframe_native_kit.intentframe_native_bundles.actions.api.constraints import ApiConstraints
    from intentframe_native_kit.intentframe_native_bundles.actions.files.constraints import FileConstraints

    analysis_engine = AIAnalysisEngine(model="gpt-4o-mini", verbose=False)
    guardian = AIGuardian(model="gpt-4o-mini", verbose=True)

    async def run_pipeline(intent, ctx):
        report = await analysis_engine.analyze(intent)
        result = await guardian.validate(intent, report, ctx)
        return result

    user_context = UserContext(
        user_id="test_domain_hardening",
        allowed_actions={
            "READ_FILE": ActionPermission(
                safe=True,
                constraints=FileConstraints(allowed_paths=["/invoices/"]),
            ),
            "PAY_INVOICE": ActionPermission(
                safe=False,
                constraints=ApiConstraints(max_amount=5000.0),
            ),
            "DELETE_FILE": ActionPermission(
                safe=False,
                constraints=FileConstraints(allowed_paths=["/tmp/*", "/cache/"]),
            ),
            "ASK_USER": ActionPermission(safe=False),
        },
        domain_constraints={
            "finance": FinanceConstraints(
                max_amount=5000.0,
                allowed_currencies=["USD"],
                allowed_recipients=["ACME Corp", "Office Depot"],
            ),
            "deletion": DeletionConstraints(
                allowed_paths=["/tmp/*", "/cache/"],
                block_irreversible=True,
            ),
        },
    )

    cases = [
        {
            "name": "PAY_INVOICE $8k → domain module BLOCK (before AI)",
            "intent": IntentFrame(
                action=ActionType.PAY_INVOICE,
                target="acme_invoice",
                data={"amount": 8000.0, "currency": "USD", "recipient": "ACME Corp"},
                reason="Paying overdue invoice",
                agent_id="test_agent",
            ),
            "expected": "BLOCK",
            "expect_domain_block": True,
        },
        {
            "name": "PAY_INVOICE $100 BTC → domain module BLOCK on currency",
            "intent": IntentFrame(
                action=ActionType.PAY_INVOICE,
                target="crypto_vendor",
                data={"amount": 100.0, "currency": "BTC"},
                reason="Paying vendor",
                agent_id="test_agent",
            ),
            "expected": "BLOCK",
            "expect_domain_block": True,
        },
        {
            "name": "PAY_INVOICE $3k USD to ACME → domain passes, AI evaluates",
            "intent": IntentFrame(
                action=ActionType.PAY_INVOICE,
                target="acme_invoice",
                data={"amount": 3000.0, "currency": "USD", "recipient": "ACME Corp"},
                reason="Paying approved invoice for office supplies",
                agent_id="test_agent",
            ),
            "expected": "ALLOW",
            "expect_domain_block": False,
        },
        {
            "name": "DELETE_FILE /important/db → domain module BLOCK on path",
            "intent": IntentFrame(
                action=ActionType.DELETE_FILE,
                target="/important/database.db",
                data={"path": "/important/database.db", "irreversible": False},
                reason="Cleaning up old data",
                agent_id="test_agent",
            ),
            "expected": "BLOCK",
            "expect_domain_block": True,
        },
        {
            "name": "DELETE_FILE /tmp/cache irreversible → domain module BLOCK",
            "intent": IntentFrame(
                action=ActionType.DELETE_FILE,
                target="/tmp/old_cache.bin",
                data={"path": "/tmp/old_cache.bin", "irreversible": True},
                reason="Removing stale cache",
                agent_id="test_agent",
            ),
            "expected": "BLOCK",
            "expect_domain_block": True,
        },
    ]

    for case in cases:
        name = case["name"]
        intent = case["intent"]
        expected = case["expected"]
        expect_domain_block = case["expect_domain_block"]

        print(f"\n  --- {name} ---")

        result = asyncio.run(run_pipeline(intent, user_context))
        decision = result.decision.value

        match = decision == expected
        check(f"Decision: {decision} (expected {expected})", match)

        if expect_domain_block and decision == "BLOCK":
            is_domain = (
                "domain" in result.message.lower()
                or "exceeds" in result.message.lower()
                or "currency" in result.message.lower()
                or "irreversible" in result.message.lower()
                or "path" in result.message.lower()
            )
            check(f"  blocked by domain module (not AI)", is_domain, result.message[:80])


# ═══════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════

def main():
    skip_ai = "--no-ai" in sys.argv

    print("=" * 60)
    print("  Domain Hardening Test Suite")
    print("=" * 60)

    test_finance_module()
    test_deletion_module()
    test_deletion_module_host_file()
    test_actor_is_thin_transport()
    test_serialization_roundtrip()
    test_taxonomy()

    if not skip_ai:
        test_guardian_pipeline()
    else:
        print("\n  [SKIPPED] AI pipeline tests (--no-ai flag)")

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed_count} passed, {failed_count} failed")
    print("=" * 60)

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
