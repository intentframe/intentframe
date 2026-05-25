#!/usr/bin/env python3
"""Deterministic gate matrix parity verifier (legacy 66e567c matched_gate pins).

Runs minimal DG fixtures, compares gate/decision rows to a frozen baseline,
and writes a human-readable audit report — same pattern as hardened prompts.

Usage:
    .venv/bin/python tests/verify_deterministic_gate_matrix.py

Artifacts:
    tests/fixtures/deterministic_gate_matrix_baseline.txt  — frozen legacy matrix
    tests/fixtures/deterministic_gate_matrix_parity_report.txt — proof / audit

Exit code 0 when baseline matches; 1 on any mismatch.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "deterministic_gate_matrix_baseline.txt"
REPORT_PATH = REPO_ROOT / "tests" / "fixtures" / "deterministic_gate_matrix_parity_report.txt"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.deterministic_gate_matrix_lib import (  # noqa: E402
    LEGACY_COMMIT,
    LEGACY_MATCHED_GATES,
    capture_gate_rows,
    format_matrix_snapshot,
    runner_phase_order_ok,
)


@dataclass(frozen=True)
class RowResult:
    gate: str
    baseline: str
    current: str
    match: bool


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_gate_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    in_rows = False
    for line in text.splitlines():
        if line.startswith("gate|decision|matched_gate|fixture"):
            in_rows = True
            continue
        if not in_rows:
            continue
        if not line.strip() or line.startswith("-") or line.startswith("="):
            in_rows = False
            continue
        if "|" not in line:
            continue
        gate, decision, matched_gate, _fixture = line.split("|", 3)
        rows[gate] = f"{decision}|{matched_gate}"
    return rows


def parse_runner_ordered(text: str) -> bool | None:
    for line in text.splitlines():
        if line.startswith("ordered="):
            return line.split("=", 1)[1].strip() == "yes"
    return None


def compare_rows(baseline: dict[str, str], current: dict[str, str]) -> list[RowResult]:
    all_gates = sorted(set(baseline) | set(current))
    results: list[RowResult] = []
    for gate in all_gates:
        base = baseline.get(gate, "<missing>")
        curr = current.get(gate, "<missing>")
        results.append(
            RowResult(gate=gate, baseline=base, current=curr, match=base == curr)
        )
    return results


def write_report(
    *,
    baseline_text: str,
    current_text: str,
    row_results: list[RowResult],
    runner_baseline: bool | None,
    runner_current: bool,
) -> None:
    passed = sum(1 for r in row_results if r.match)
    failed = len(row_results) - passed
    runner_match = runner_baseline is None or runner_baseline == runner_current
    overall = failed == 0 and runner_match and passed == len(LEGACY_MATCHED_GATES)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "DETERMINISTIC GATE MATRIX PARITY REPORT",
        "=" * 72,
        f"Generated:        {now}",
        f"Legacy baseline:    {BASELINE_PATH}",
        f"Legacy commit:      {LEGACY_COMMIT}",
        f"Verify script:      tests/verify_deterministic_gate_matrix.py",
        "",
        f"OVERALL:            {'PASS' if overall else 'FAIL'}  "
        f"({passed}/{len(row_results)} gate rows match)",
        "",
        "GATE ROW DETAILS",
        "-" * 72,
    ]

    for r in row_results:
        status = "PASS" if r.match else "FAIL"
        lines.append(f"[{status}] {r.gate}")
        lines.append(f"       baseline: {r.baseline}")
        lines.append(f"       current:  {r.current}")
        lines.append("")

    lines.extend([
        "RUNNER PHASE ORDER",
        "-" * 72,
        f"baseline ordered: {'yes' if runner_baseline else 'no' if runner_baseline is not None else 'n/a'}",
        f"current  ordered: {'yes' if runner_current else 'no'}",
        f"match:            {'PASS' if runner_match else 'FAIL'}",
        "",
        "SNAPSHOT HASHES",
        "-" * 72,
        f"baseline sha256: {sha256(baseline_text)}",
        f"current  sha256: {sha256(current_text)}",
        "",
    ])

    if overall:
        lines.append("All gate rows and runner phase order match the legacy baseline.")
        lines.append(f"Deterministic gate parity with legacy {LEGACY_COMMIT} is VERIFIED.")
    else:
        lines.append("MISMATCH — see FAIL rows above.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not BASELINE_PATH.is_file():
        print(
            f"ERROR: missing baseline at {BASELINE_PATH}\n"
            f"Run: .venv/bin/python tests/verify_deterministic_gate_matrix.py --write-baseline",
            file=sys.stderr,
        )
        return 1

    baseline_text = BASELINE_PATH.read_text(encoding="utf-8")
    rows = capture_gate_rows()
    runner_ok = runner_phase_order_ok()
    current_text = format_matrix_snapshot(rows, runner_ok=runner_ok)

    baseline_rows = parse_gate_rows(baseline_text)
    current_rows = parse_gate_rows(current_text)
    row_results = compare_rows(baseline_rows, current_rows)
    runner_baseline = parse_runner_ordered(baseline_text)

    write_report(
        baseline_text=baseline_text,
        current_text=current_text,
        row_results=row_results,
        runner_baseline=runner_baseline,
        runner_current=runner_ok,
    )

    passed = sum(1 for r in row_results if r.match)
    failed = len(row_results) - passed
    runner_match = runner_baseline is None or runner_baseline == runner_ok
    overall = failed == 0 and runner_match

    print(f"Wrote report: {REPORT_PATH}")
    print(f"Gate rows: {passed} passed, {failed} failed (of {len(row_results)})")
    print(f"Runner phase order: {'PASS' if runner_ok else 'FAIL'}")

    for r in row_results:
        mark = "✓" if r.match else "✗"
        print(f"  {mark} {r.gate}: {r.current}")

    return 0 if overall else 1


def write_baseline() -> int:
    rows = capture_gate_rows()
    runner_ok = runner_phase_order_ok()
    snapshot = format_matrix_snapshot(rows, runner_ok=runner_ok)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(snapshot, encoding="utf-8")
    print(f"Wrote baseline: {BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--write-baseline":
        raise SystemExit(write_baseline())
    raise SystemExit(main())
