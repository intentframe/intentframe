"""Pytest entry points for deterministic gate matrix parity."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.deterministic_gate_matrix_lib import (
    LEGACY_MATCHED_GATES,
    _dg,
    gate_cases,
    runner_phase_order_ok,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "tests" / "verify_deterministic_gate_matrix.py"


def test_deterministic_gate_matrix_matches_legacy_baseline() -> None:
    """Frozen baseline + audit report (see verify_deterministic_gate_matrix.py)."""
    proc = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("case", gate_cases(), ids=lambda case: case.gate)
def test_legacy_matched_gate_matrix(case) -> None:
    """Live DG run — fast failure without invoking the verify script."""
    result = case.run(_dg())
    assert result.decision is case.decision
    assert result.matched_gate == case.gate


def test_matrix_covers_all_legacy_gates() -> None:
    covered = {case.gate for case in gate_cases()}
    assert covered == LEGACY_MATCHED_GATES


def test_runner_phase_order_matches_legacy() -> None:
    assert runner_phase_order_ok()
