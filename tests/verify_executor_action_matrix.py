#!/usr/bin/env python3
"""Executor action matrix parity verifier (pre-extraction baseline pins).

Runs deterministic adapter fixtures, compares rows to a frozen baseline,
and writes a human-readable audit report — same pattern as the DG gate matrix.

Usage:
    .venv/bin/python tests/verify_executor_action_matrix.py
    .venv/bin/python tests/verify_executor_action_matrix.py --write-baseline

Artifacts:
    tests/fixtures/executor_action_matrix_baseline.txt
    tests/fixtures/executor_action_matrix_parity_report.txt
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "executor_action_matrix_baseline.txt"
REPORT_PATH = REPO_ROOT / "tests" / "fixtures" / "executor_action_matrix_parity_report.txt"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.executor_action_matrix_lib import (  # noqa: E402
    ACTION_CASE_IDS,
    BASELINE_COMMIT,
    assert_baseline_commit_matches,
    capture_action_rows,
    capture_manifest_rows,
    format_matrix_snapshot,
    gateway_uses_safe_execute,
    parse_action_rows,
    parse_manifest_rows,
    parse_safe_execute_contract,
    require_darwin,
)


@dataclass(frozen=True)
class RowResult:
    key: str
    section: str
    baseline: str
    current: str
    match: bool


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compare_maps(
    section: str,
    baseline: dict[str, str],
    current: dict[str, str],
) -> list[RowResult]:
    all_keys = sorted(set(baseline) | set(current))
    results: list[RowResult] = []
    for key in all_keys:
        base = baseline.get(key, "<missing>")
        curr = current.get(key, "<missing>")
        results.append(
            RowResult(
                key=key,
                section=section,
                baseline=base,
                current=curr,
                match=base == curr,
            )
        )
    return results


def write_report(
    *,
    baseline_text: str,
    current_text: str,
    row_results: list[RowResult],
    contract_baseline: bool | None,
    contract_current: bool,
) -> None:
    passed = sum(1 for r in row_results if r.match)
    failed = len(row_results) - passed
    contract_match = contract_baseline is None or contract_baseline == contract_current
    action_pass = all(r.match for r in row_results if r.section == "action")
    manifest_pass = all(r.match for r in row_results if r.section == "manifest")
    overall = (
        failed == 0
        and contract_match
        and action_pass
        and manifest_pass
        and len([r for r in row_results if r.section == "action"]) == len(ACTION_CASE_IDS)
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "EXECUTOR ACTION MATRIX PARITY REPORT",
        "=" * 72,
        f"Generated:          {now}",
        f"Baseline fixture:   {BASELINE_PATH}",
        f"Baseline commit:    {BASELINE_COMMIT}",
        f"Verify script:      tests/verify_executor_action_matrix.py",
        "",
        f"OVERALL:            {'PASS' if overall else 'FAIL'}  "
        f"({passed}/{len(row_results)} rows match)",
        "",
        "ROW DETAILS",
        "-" * 72,
    ]

    for r in row_results:
        status = "PASS" if r.match else "FAIL"
        lines.append(f"[{status}] {r.section}:{r.key}")
        lines.append(f"       baseline: {r.baseline}")
        lines.append(f"       current:  {r.current}")
        lines.append("")

    lines.extend([
        "EXECUTION CONTRACT",
        "-" * 72,
        f"baseline safe_execute: {'yes' if contract_baseline else 'no' if contract_baseline is not None else 'n/a'}",
        f"current  safe_execute: {'yes' if contract_current else 'no'}",
        f"match:                 {'PASS' if contract_match else 'FAIL'}",
        "",
        "SNAPSHOT HASHES",
        "-" * 72,
        f"baseline sha256: {sha256(baseline_text)}",
        f"current  sha256: {sha256(current_text)}",
        "",
    ])

    if overall:
        lines.append("All action/manifest rows and execution contract match the baseline.")
        lines.append(f"Executor action parity with commit {BASELINE_COMMIT} is VERIFIED.")
    else:
        lines.append("MISMATCH — see FAIL rows above.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        require_darwin()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not BASELINE_PATH.is_file():
        print(
            f"ERROR: missing baseline at {BASELINE_PATH}\n"
            f"Run: .venv/bin/python tests/verify_executor_action_matrix.py --write-baseline",
            file=sys.stderr,
        )
        return 1

    try:
        assert_baseline_commit_matches()
    except AssertionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    baseline_text = BASELINE_PATH.read_text(encoding="utf-8")
    action_rows = capture_action_rows()
    manifest_rows = capture_manifest_rows()
    contract_ok = gateway_uses_safe_execute()
    current_text = format_matrix_snapshot(
        action_rows,
        manifest_rows,
        safe_execute_ok=contract_ok,
    )

    row_results = compare_maps(
        "action",
        parse_action_rows(baseline_text),
        parse_action_rows(current_text),
    )
    row_results.extend(
        compare_maps(
            "manifest",
            parse_manifest_rows(baseline_text),
            parse_manifest_rows(current_text),
        )
    )

    contract_baseline = parse_safe_execute_contract(baseline_text)
    write_report(
        baseline_text=baseline_text,
        current_text=current_text,
        row_results=row_results,
        contract_baseline=contract_baseline,
        contract_current=contract_ok,
    )

    passed = sum(1 for r in row_results if r.match)
    failed = len(row_results) - passed
    contract_match = contract_baseline is None or contract_baseline == contract_ok
    overall = failed == 0 and contract_match

    print(f"Wrote report: {REPORT_PATH}")
    print(f"Rows: {passed} passed, {failed} failed (of {len(row_results)})")
    print(f"Worker pool safe_execute contract: {'PASS' if contract_ok else 'FAIL'}")

    for r in row_results:
        mark = "✓" if r.match else "✗"
        print(f"  {mark} {r.section}:{r.key}: {r.current}")

    return 0 if overall else 1


def write_baseline() -> int:
    try:
        require_darwin()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    action_rows = capture_action_rows()
    manifest_rows = capture_manifest_rows()
    contract_ok = gateway_uses_safe_execute()
    snapshot = format_matrix_snapshot(
        action_rows,
        manifest_rows,
        safe_execute_ok=contract_ok,
    )
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(snapshot, encoding="utf-8")
    print(f"Wrote baseline: {BASELINE_PATH}")
    print(f"Action cases: {len(action_rows)}")
    print(f"Manifest adapters: {len(manifest_rows)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--write-baseline":
        raise SystemExit(write_baseline())
    raise SystemExit(main())
