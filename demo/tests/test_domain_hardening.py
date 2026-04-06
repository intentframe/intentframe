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

from action_registry import ActionType
from action_registry.types import DomainType, ACTION_DOMAINS
from intentframe_core.types import IntentFrame
from intentframe_core.domains import DOMAIN_SCHEMAS
from policy_registry.models import UserPolicy
from policy_registry.domains.finance import FinanceConstraints
from policy_registry.domains.deletion import DeletionConstraints
from intentframe_components.guardian.domains.finance import FinanceModule
from intentframe_components.guardian.domains.deletion import DeletionModule


passed_count = 0
failed_count = 0


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

    module = FinanceModule()
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
    ok, reason = module.check(intent, constraints)
    check("Amount $8k > $5k limit → BLOCK", not ok)
    check("  reason mentions limit", "exceeds" in reason.lower())

    # Amount within limit → pass (structurally valid)
    intent2 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="acme_invoice",
        data={"amount": 3000.0, "currency": "USD", "recipient": "ACME Corp"},
    )
    ok2, _ = module.check(intent2, constraints)
    check("Amount $3k < $5k limit → pass", ok2)

    # Wrong currency → BLOCK
    intent3 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="crypto_vendor",
        data={"amount": 100.0, "currency": "BTC"},
    )
    ok3, reason3 = module.check(intent3, constraints)
    check("Currency BTC not in [USD, EUR] → BLOCK", not ok3)
    check("  reason mentions currency", "currency" in reason3.lower())

    # Wrong recipient → BLOCK
    intent4 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="shady_vendor",
        data={"amount": 100.0, "currency": "USD", "recipient": "Unknown LLC"},
    )
    ok4, reason4 = module.check(intent4, constraints)
    check("Recipient 'Unknown LLC' not in allowlist → BLOCK", not ok4)

    # No recipient specified → pass (optional field)
    intent5 = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="vendor",
        data={"amount": 100.0, "currency": "USD"},
    )
    ok5, _ = module.check(intent5, constraints)
    check("No recipient (optional) → pass", ok5)

    # Base DomainConstraints (not FinanceConstraints) → pass
    from policy_registry.domains.base import DomainConstraints
    base = DomainConstraints(domain=DomainType.FINANCE)
    ok6, _ = module.check(intent, base)
    check("Base DomainConstraints → pass (isinstance guard)", ok6)


def test_deletion_module():
    print("\n" + "=" * 60)
    print("  1b. Deletion Module — structural enforcement")
    print("=" * 60)

    module = DeletionModule()
    constraints = DeletionConstraints(
        allowed_paths=["/tmp/*", "/cache/"],
        block_irreversible=True,
    )

    # Path not in allowed list → BLOCK
    intent = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/important/database.db",
        data={"target_path": "/important/database.db", "irreversible": False},
    )
    ok, reason = module.check(intent, constraints)
    check("Path /important/database.db not in [/tmp/*, /cache/] → BLOCK", not ok)
    check("  reason mentions path", "path" in reason.lower())

    # Path matches glob → check passes path, but irreversible → BLOCK
    intent2 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/scratch.log",
        data={"target_path": "/tmp/scratch.log", "irreversible": True},
    )
    ok2, reason2 = module.check(intent2, constraints)
    check("Path /tmp/scratch.log matches, but irreversible=True → BLOCK", not ok2)
    check("  reason mentions irreversible", "irreversible" in reason2.lower())

    # Path matches, reversible → pass
    intent3 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/tmp/scratch.log",
        data={"target_path": "/tmp/scratch.log", "irreversible": False},
    )
    ok3, _ = module.check(intent3, constraints)
    check("Path matches, irreversible=False → pass", ok3)

    # Path with prefix match → pass
    intent4 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/cache/old_data.bin",
        data={"target_path": "/cache/old_data.bin", "irreversible": False},
    )
    ok4, _ = module.check(intent4, constraints)
    check("Path /cache/old_data.bin prefix matches /cache/ → pass", ok4)

    # No allowed_paths constraint → only check irreversible
    constraints2 = DeletionConstraints(block_irreversible=False)
    intent5 = IntentFrame(
        action=ActionType.DELETE_FILE,
        target="/anywhere/file.txt",
        data={"target_path": "/anywhere/file.txt", "irreversible": True},
    )
    ok5, _ = module.check(intent5, constraints2)
    check("No path restriction, block_irreversible=False → pass", ok5)


# ═══════════════════════════════════════════════════════════════════
# 2. Actor Schema Validation (no server)
# ═══════════════════════════════════════════════════════════════════

def test_actor_schema_validation():
    print("\n" + "=" * 60)
    print("  2. Actor Schema Validation — _build_intent")
    print("=" * 60)

    from intentframe_actor import Actor
    actor = Actor(agent_id="test", user_id="test")

    # PAY_INVOICE with valid data → should succeed
    intent = actor._build_intent({
        "action": "PAY_INVOICE",
        "target": "vendor_invoice",
        "reason": "test",
        "data": {"amount": 5000.0, "currency": "USD"},
    })
    check("PAY_INVOICE with amount+currency → builds OK", intent is not None)
    check("  action is PAY_INVOICE", intent.action == ActionType.PAY_INVOICE)

    # PAY_INVOICE missing amount → should raise ValueError
    raised = False
    msg = ""
    try:
        actor._build_intent({
            "action": "PAY_INVOICE",
            "target": "vendor",
            "reason": "test",
            "data": {"description": "no amount field"},
        })
    except ValueError as e:
        raised = True
        msg = str(e)
    check("PAY_INVOICE without amount → ValueError", raised)
    check("  error mentions FinancialIntentData", "FinancialIntentData" in msg)

    # DELETE_FILE with valid data → should succeed
    intent2 = actor._build_intent({
        "action": "DELETE_FILE",
        "target": "/tmp/file.txt",
        "reason": "cleanup",
        "data": {"target_path": "/tmp/file.txt"},
    })
    check("DELETE_FILE with target_path → builds OK", intent2 is not None)

    # DELETE_FILE missing target_path → should raise ValueError
    raised2 = False
    try:
        actor._build_intent({
            "action": "DELETE_FILE",
            "target": "/tmp/file.txt",
            "reason": "cleanup",
            "data": {"filename": "file.txt"},
        })
    except ValueError as e:
        raised2 = True
    check("DELETE_FILE without target_path → ValueError", raised2)

    # Non-critical-domain action → no schema validation
    intent3 = actor._build_intent({
        "action": "READ_FILE",
        "target": "/invoices/test.md",
        "reason": "reading",
    })
    check("READ_FILE (no domain) → builds OK without schema", intent3 is not None)


# ═══════════════════════════════════════════════════════════════════
# 3. Serialization Round-Trip (no server)
# ═══════════════════════════════════════════════════════════════════

def test_serialization_roundtrip():
    print("\n" + "=" * 60)
    print("  3. Serialization Round-Trip — JSON discriminated union")
    print("=" * 60)

    policy = UserPolicy(
        user_id="test_user",
        domain_constraints={
            "finance": FinanceConstraints(
                max_amount=5000.0,
                allowed_currencies=["USD", "EUR"],
                allowed_recipients=["ACME Corp"],
            ),
            "deletion": DeletionConstraints(
                require_confirmation=True,
                block_irreversible=True,
                allowed_paths=["/tmp/*"],
            ),
        },
    )

    json_str = policy.model_dump_json()
    restored = UserPolicy.model_validate_json(json_str)

    fc = restored.domain_constraints.get("finance")
    dc = restored.domain_constraints.get("deletion")

    check("Finance constraints survive round-trip", fc is not None)
    check("  isinstance FinanceConstraints", isinstance(fc, FinanceConstraints))
    if isinstance(fc, FinanceConstraints):
        check("  max_amount preserved", fc.max_amount == 5000.0)
        check("  allowed_currencies preserved", fc.allowed_currencies == ["USD", "EUR"])
        check("  allowed_recipients preserved", fc.allowed_recipients == ["ACME Corp"])

    check("Deletion constraints survive round-trip", dc is not None)
    check("  isinstance DeletionConstraints", isinstance(dc, DeletionConstraints))
    if isinstance(dc, DeletionConstraints):
        check("  require_confirmation preserved", dc.require_confirmation is True)
        check("  block_irreversible preserved", dc.block_irreversible is True)
        check("  allowed_paths preserved", dc.allowed_paths == ["/tmp/*"])

    # Verify domain modules work with deserialized constraints
    module = FinanceModule()
    intent = IntentFrame(
        action=ActionType.PAY_INVOICE,
        target="test",
        data={"amount": 8000.0, "currency": "USD"},
    )
    ok, reason = module.check(intent, fc)
    check("Finance module works with deserialized constraints", not ok)
    check("  blocks $8k against $5k limit", "exceeds" in reason.lower())


# ═══════════════════════════════════════════════════════════════════
# 4. Taxonomy — ACTION_DOMAINS and DOMAIN_SCHEMAS consistency
# ═══════════════════════════════════════════════════════════════════

def test_taxonomy():
    print("\n" + "=" * 60)
    print("  4. Taxonomy — ACTION_DOMAINS and DOMAIN_SCHEMAS")
    print("=" * 60)

    check("PAY_INVOICE mapped to FINANCE", ACTION_DOMAINS.get(ActionType.PAY_INVOICE) == DomainType.FINANCE)
    check("DELETE_FILE mapped to DELETION", ACTION_DOMAINS.get(ActionType.DELETE_FILE) == DomainType.DELETION)
    check("READ_FILE not in ACTION_DOMAINS", ActionType.READ_FILE not in ACTION_DOMAINS)

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
    from policy_registry.constraints import FileConstraints, ApiConstraints

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
                data={"target_path": "/important/database.db", "irreversible": False},
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
                data={"target_path": "/tmp/old_cache.bin", "irreversible": True},
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
    test_actor_schema_validation()
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
