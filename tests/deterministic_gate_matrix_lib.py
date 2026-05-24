"""Shared fixtures + capture for deterministic gate matrix parity.

Pre-refactor baseline: ``66e567c`` (``pre-refactor`` tag).
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Callable

from action_registry.types import ActionType
from intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_components.guardian.deterministic import (
    DeterministicDecision,
    DeterministicGuardian,
    DeterministicResult,
)
from intentframe_core.types import IntentFrame, UserContext
from intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints
from policy_registry.models import ActionPermission
from tests.deterministic_accuracy._helpers import (
    decide_dg_sync,
    run_dg,
    run_dg_with_intel,
)

LEGACY_COMMIT = "66e567c"

LEGACY_MATCHED_GATES: frozenset[str] = frozenset({
    "permission",
    "constraint",
    "domain",
    "command_shield",
    "write_file_sensitive_path",
    "write_host_file_floor",
    "delete_host_file_floor",
    "passive_read",
    "run_command_read_only",
})

LEGACY_RUNNER_CALL_PATTERNS: tuple[str, ...] = (
    r"bundle\.prepare_evidence",
    r"bundle\.enrich",
    r"bundle\.enforce_constraints",
    r"domain_bundle\.enforce",
    r"bundle\.structural_gates",
    r"_try_passive_read_allow",
    r"bundle\.allow_gates",
)


@dataclass(frozen=True)
class GateRow:
    gate: str
    decision: str
    matched_gate: str
    fixture: str


@dataclass(frozen=True)
class GateCase:
    gate: str
    decision: DeterministicDecision
    fixture: str
    run: Callable[[DeterministicGuardian], DeterministicResult]


def _dg() -> DeterministicGuardian:
    return DeterministicGuardian()


def _intent(action: ActionType, target: str = "", **data) -> IntentFrame:
    return IntentFrame(
        action=action,
        target=target,
        data=dict(data) if data else None,
        reason="gate matrix",
        agent_id="gate_matrix",
    )


def _user(**actions: ActionPermission) -> UserContext:
    return UserContext(user_id="gate_matrix", allowed_actions=dict(actions))


def gate_cases() -> tuple[GateCase, ...]:
    perm_unsafe = ActionPermission(safe=False)
    perm_safe = ActionPermission(safe=True)

    def permission_block(dg: DeterministicGuardian) -> DeterministicResult:
        return decide_dg_sync(
            dg,
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(),
        )

    def constraint_block(dg: DeterministicGuardian) -> DeterministicResult:
        constraints = TerminalConstraints(blocked_patterns=["sudo"])
        return run_dg_with_intel(
            "sudo ls",
            _user(
                RUN_COMMAND=ActionPermission(
                    safe=False,
                    constraints=constraints.model_dump(mode="python"),
                )
            ),
            CommandIntel(verdict="SAFE", capabilities=()),
            dg,
        )

    def domain_block(dg: DeterministicGuardian) -> DeterministicResult:
        return decide_dg_sync(
            dg,
            _intent(ActionType.DELETE_FILE, "/tmp/foo", irreversible=True),
            UserContext(
                user_id="gate_matrix",
                allowed_actions={"DELETE_FILE": perm_unsafe},
                domain_constraints={
                    "deletion": {"block_irreversible": True},
                },
            ),
        )

    def command_shield_block(dg: DeterministicGuardian) -> DeterministicResult:
        result, _ = run_dg(
            "sudo rm -rf /",
            _user(RUN_COMMAND=perm_unsafe),
            dg,
        )
        return result

    def write_file_sensitive_path_block(dg: DeterministicGuardian) -> DeterministicResult:
        return decide_dg_sync(
            dg,
            _intent(ActionType.WRITE_FILE, "/home/.zshrc"),
            _user(WRITE_FILE=perm_safe),
        )

    def write_host_file_floor_block(dg: DeterministicGuardian) -> DeterministicResult:
        from resource_registry.floor import (
            DENY_WRITE_PREFIXES,
            canonicalize_real_path,
        )

        canonical = canonicalize_real_path("/etc/sudoers")
        assert canonical in DENY_WRITE_PREFIXES or any(
            canonical == p or canonical.startswith(p + "/")
            for p in DENY_WRITE_PREFIXES
        )
        return decide_dg_sync(
            dg,
            _intent(ActionType.WRITE_HOST_FILE, "/etc/sudoers"),
            _user(WRITE_HOST_FILE=perm_unsafe),
        )

    def delete_host_file_floor_block(dg: DeterministicGuardian) -> DeterministicResult:
        from resource_registry.floor import (
            DENY_WRITE_PREFIXES,
            canonicalize_real_path,
        )

        canonical = canonicalize_real_path("/etc/sudoers")
        assert canonical in DENY_WRITE_PREFIXES or any(
            canonical == p or canonical.startswith(p + "/")
            for p in DENY_WRITE_PREFIXES
        )
        return decide_dg_sync(
            dg,
            _intent(ActionType.DELETE_HOST_FILE, "/etc/sudoers"),
            _user(DELETE_HOST_FILE=perm_unsafe),
        )

    def passive_read_allow(dg: DeterministicGuardian) -> DeterministicResult:
        return decide_dg_sync(
            dg,
            _intent(ActionType.READ_FILE, "/tmp/x"),
            _user(READ_FILE=perm_safe),
        )

    def run_command_read_only_allow(dg: DeterministicGuardian) -> DeterministicResult:
        return run_dg_with_intel(
            "ls -la",
            _user(RUN_COMMAND=perm_unsafe),
            CommandIntel(
                verdict="SAFE",
                capabilities=("capability:read_only:filesystem_list",),
            ),
            dg,
        )

    return (
        GateCase("permission", DeterministicDecision.BLOCK, "READ_FILE denied", permission_block),
        GateCase("constraint", DeterministicDecision.BLOCK, "RUN_COMMAND sudo blocked_pattern", constraint_block),
        GateCase("domain", DeterministicDecision.BLOCK, "DELETE_FILE irreversible", domain_block),
        GateCase("command_shield", DeterministicDecision.BLOCK, "RUN_COMMAND catastrophic", command_shield_block),
        GateCase(
            "write_file_sensitive_path",
            DeterministicDecision.BLOCK,
            "WRITE_FILE ~/.zshrc",
            write_file_sensitive_path_block,
        ),
        GateCase(
            "write_host_file_floor",
            DeterministicDecision.BLOCK,
            "WRITE_HOST_FILE /etc/sudoers",
            write_host_file_floor_block,
        ),
        GateCase(
            "delete_host_file_floor",
            DeterministicDecision.BLOCK,
            "DELETE_HOST_FILE /etc/sudoers",
            delete_host_file_floor_block,
        ),
        GateCase("passive_read", DeterministicDecision.ALLOW, "READ_FILE safe=True", passive_read_allow),
        GateCase(
            "run_command_read_only",
            DeterministicDecision.ALLOW,
            "RUN_COMMAND read_only cap",
            run_command_read_only_allow,
        ),
    )


def capture_gate_rows() -> tuple[GateRow, ...]:
    dg = _dg()
    rows: list[GateRow] = []
    for case in gate_cases():
        result = case.run(dg)
        rows.append(
            GateRow(
                gate=case.gate,
                decision=result.decision.value,
                matched_gate=result.matched_gate,
                fixture=case.fixture,
            )
        )
    return tuple(rows)


def capture_runner_phase_patterns() -> tuple[str, ...]:
    from intentframe_bundle_sdk.runner import DeterministicRunner

    source = inspect.getsource(DeterministicRunner.run_action_bundle)
    return LEGACY_RUNNER_CALL_PATTERNS


def runner_phase_order_ok() -> bool:
    from intentframe_bundle_sdk.runner import DeterministicRunner

    source = inspect.getsource(DeterministicRunner.run_action_bundle)
    positions = [
        re.search(pattern, source).start()  # type: ignore[union-attr]
        for pattern in LEGACY_RUNNER_CALL_PATTERNS
    ]
    return positions == sorted(positions)


def format_matrix_snapshot(rows: tuple[GateRow, ...], *, runner_ok: bool) -> str:
    lines = [
        "DETERMINISTIC GATE MATRIX",
        "=" * 72,
        f"Legacy commit: {LEGACY_COMMIT}",
        "",
        "GATE ROWS",
        "-" * 72,
        "gate|decision|matched_gate|fixture",
    ]
    for row in rows:
        lines.append(
            f"{row.gate}|{row.decision}|{row.matched_gate}|{row.fixture}"
        )
    lines.extend([
        "",
        "RUNNER PHASE ORDER",
        "-" * 72,
        f"ordered={'yes' if runner_ok else 'no'}",
    ])
    for pattern in LEGACY_RUNNER_CALL_PATTERNS:
        lines.append(f"  {pattern}")
    return "\n".join(lines) + "\n"
