"""Pytest entry point for per-action AE/Guardian prompt routing parity."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "tests" / "verify_prompt_routing_parity.py"


def test_prompt_routing_matches_legacy_baseline() -> None:
    proc = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
