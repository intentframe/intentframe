"""Pytest entry point for hardened-prompt parity verification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "tests" / "verify_hardened_prompts_parity.py"


def test_hardened_prompts_match_legacy_baseline() -> None:
    proc = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
