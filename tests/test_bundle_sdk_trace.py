"""Tests for Bundle SDK lifecycle trace logging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from action_registry.types import ActionType
from intentframe_bundle_sdk.registry import domain_bundle_for, validate_policy_domain_constraints
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.trace import (
    configure_trace_logging,
    emit_skip,
    reset_trace_logging,
    traced_acall,
    traced_call,
)
from intentframe_bundle_sdk.types import ActionPermission, BundleContext, BundlePhaseOutcome
from intentframe_core.types import IntentFrame, UserContext
from tests._bundle_loader import ensure_test_bundles_loaded


@pytest.fixture
def trace_log(tmp_path: Path) -> Path:
    reset_trace_logging()
    configure_trace_logging(tmp_path)
    log_path = tmp_path / "bundle-sdk.log"
    yield log_path
    reset_trace_logging()


def _read_records(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _intent() -> IntentFrame:
    return IntentFrame(
        action=ActionType.RUN_COMMAND,
        target="echo hi",
        reason="trace test",
        agent_id="trace_tester",
        session_id="sess_abc123",
        sequence_id=7,
    )


def test_traced_call_binds_inputs_and_output(trace_log: Path) -> None:
    def add(a: int, b: int = 0) -> int:
        return a + b

    assert traced_call(add, 2, b=3, lane="boot", trace_id="t:1", phase="add") == 5
    rec = _read_records(trace_log)[0]
    assert rec["lane"] == "boot"
    assert rec["phase"] == "add"
    assert rec["trace_id"] == "t:1"
    assert rec["inputs"] == {"a": 2, "b": 3}
    assert rec["output"] == 5
    assert rec["raised"] is None
    assert rec["skipped"] is False
    assert rec["terminal"] is False


def test_traced_call_records_exception(trace_log: Path) -> None:
    def boom() -> None:
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        traced_call(boom, lane="boot", trace_id="t:1", phase="boom")

    rec = _read_records(trace_log)[0]
    assert rec["raised"] == "ValueError('bad')"
    assert rec["output"] is None
    assert rec["terminal"] is False


@pytest.mark.asyncio
async def test_traced_acall_async_hook(trace_log: Path) -> None:
    async def greet(name: str) -> str:
        return f"hi {name}"

    result = await traced_acall(
        greet, "world", lane="lifecycle", trace_id="t:2", phase="greet"
    )
    assert result == "hi world"
    rec = _read_records(trace_log)[0]
    assert rec["inputs"] == {"name": "world"}
    assert rec["output"] == "hi world"
    assert rec["terminal"] is False


def test_emit_skip(trace_log: Path) -> None:
    emit_skip(
        lane="runtime",
        trace_id="t:3",
        phase="enforce_constraints",
        reason="no constraints",
    )
    rec = _read_records(trace_log)[0]
    assert rec["skipped"] is True
    assert rec["skipped_reason"] == "no constraints"
    assert rec["inputs"] is None
    assert rec["terminal"] is False


def test_terminal_from_marks_decisive_hooks(trace_log: Path) -> None:
    ctx = BundleContext(intent=_intent())

    def allow_gate() -> BundlePhaseOutcome:
        return BundlePhaseOutcome.allow(ctx, reason="ok", matched_gate="test_gate")

    traced_call(
        allow_gate,
        lane="runtime",
        trace_id="t:4",
        phase="allow_gates",
        terminal_from=lambda r: r.terminal,
    )
    rec = _read_records(trace_log)[0]
    assert rec["terminal"] is True
    assert rec["output"]["decision"] == "ALLOW"


def test_terminal_from_false_for_continue(trace_log: Path) -> None:
    ctx = BundleContext(intent=_intent())

    def continue_gate() -> BundlePhaseOutcome:
        return BundlePhaseOutcome.continue_(ctx)

    traced_call(
        continue_gate,
        lane="runtime",
        trace_id="t:5",
        phase="structural_gates",
        terminal_from=lambda r: r.terminal,
    )
    rec = _read_records(trace_log)[0]
    assert rec["terminal"] is False
    assert rec["output"]["decision"] == "CONTINUE"


@pytest.fixture(autouse=True)
def _load_bundles() -> None:
    ensure_test_bundles_loaded()


def test_validate_policy_domain_constraints_traces_domain_validate(
    trace_log: Path,
) -> None:
    validate_policy_domain_constraints({"finance": {"max_amount": 5000.0}})
    validate_records = [
        r for r in _read_records(trace_log) if r["phase"] == "validate"
    ]
    assert len(validate_records) == 1
    rec = validate_records[0]
    assert rec["lane"] == "boot"
    assert rec["trace_id"].startswith("boot:finance:")
    assert rec["inputs"]["domain_constraints"] == {"max_amount": 5000.0}
    assert rec["terminal"] is False


@pytest.mark.asyncio
async def test_build_constraint_prompt_context_traces_domain_describe(
    trace_log: Path,
) -> None:
    from intentframe_bundle_sdk.registry import action_bundle_for

    bundle = action_bundle_for(ActionType.PAY_INVOICE.value)
    assert bundle is not None
    permission = ActionPermission(safe=False, constraints={"max_amount": 100.0})
    user_context = UserContext(
        user_id="u1",
        allowed_actions={},
        domain_constraints={"finance": {"max_amount": 5000.0}},
    )

    await DeterministicRunner.build_constraint_prompt_context(
        bundle,
        permission,
        ("finance",),
        user_context,
        trace_id="runtime:test:1:api",
    )

    describe_records = [
        r for r in _read_records(trace_log) if r["phase"] == "domain_describe:finance"
    ]
    assert len(describe_records) == 1
    rec = describe_records[0]
    assert rec["lane"] == "runtime"
    assert rec["trace_id"] == "runtime:test:1:api"
    assert rec["inputs"]["domain_constraints"] == {"max_amount": 5000.0}
    assert rec["terminal"] is False


def test_domain_describe_traced_via_registry_bundle(trace_log: Path) -> None:
    bundle = domain_bundle_for("finance")
    assert bundle is not None
    traced_call(
        bundle.describe,
        {"max_amount": 123.0},
        lane="runtime",
        trace_id="runtime:manual",
        phase="domain_describe:finance",
    )
    rec = _read_records(trace_log)[0]
    assert rec["inputs"]["domain_constraints"] == {"max_amount": 123.0}
