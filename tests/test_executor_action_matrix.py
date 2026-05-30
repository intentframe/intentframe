"""Pytest entry points for executor action matrix parity."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.executor_action_matrix_lib import (
    ACTION_CASE_IDS,
    action_cases,
    assert_baseline_commit_matches,
    capture_action_rows,
    gateway_uses_safe_execute,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "tests" / "verify_executor_action_matrix.py"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="executor action matrix requires macOS",
)


def test_baseline_commit_matches_lib_constant() -> None:
    assert_baseline_commit_matches()


def test_executor_action_matrix_matches_baseline() -> None:
    """Frozen baseline + audit report (see verify_executor_action_matrix.py)."""
    proc = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("case", action_cases(), ids=lambda case: case.case_id)
def test_action_matrix_case(case) -> None:
    """Live adapter run — fast failure without invoking the verify script."""
    result = case.run()
    rows = {row.case_id: row for row in capture_action_rows()}
    expected = rows[case.case_id]
    assert result.success is expected.success, (
        f"{case.case_id}: expected success={expected.success}, "
        f"got {result.success}, error={result.error!r}"
    )
    assert result.rollback_available == (expected.rollback_available == "true"), (
        f"{case.case_id}: rollback_available mismatch"
    )


def test_matrix_covers_all_action_cases() -> None:
    covered = {case.case_id for case in action_cases()}
    assert covered == ACTION_CASE_IDS


def test_worker_pool_uses_safe_execute() -> None:
    assert gateway_uses_safe_execute()
