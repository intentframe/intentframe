#!/usr/bin/env python3
"""
Deterministic prompt-routing parity verifier.

Runs tests/inspect_prompt_routing.py and compares output to the frozen
legacy baseline captured from commit 66e567c.

Usage:
    .venv/bin/python tests/verify_prompt_routing_parity.py

Artifacts:
    tests/fixtures/prompt_routing_legacy_baseline.txt  — frozen legacy output
    tests/fixtures/prompt_routing_parity_report.txt     — human-readable proof

Exit code 0 when routing rows and prompt bodies match; 1 on any mismatch.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSPECT_SCRIPT = REPO_ROOT / "tests" / "inspect_prompt_routing.py"
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "prompt_routing_legacy_baseline.txt"
REPORT_PATH = REPO_ROOT / "tests" / "fixtures" / "prompt_routing_parity_report.txt"
LEGACY_COMMIT = "66e567c"

ROUTING_HEADER = (
    "action|ae_prompt_id|guardian_prompt_id|ae_system_sha256|guardian_system_sha256"
)
AE_BODIES_HEADER = "AE SYSTEM PROMPT BODIES"
GUARDIAN_BODIES_HEADER = "GUARDIAN SYSTEM PROMPT BODIES"


@dataclass(frozen=True)
class RowResult:
    action: str
    baseline: str
    current: str
    match: bool
    first_diff_line: str | None = None


@dataclass(frozen=True)
class BlockResult:
    name: str
    baseline_hash: str
    current_hash: str
    baseline_chars: int
    current_chars: int
    match: bool
    first_diff_line: str | None = None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def first_diff(a: str, b: str) -> str | None:
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    for i, (la, lb) in enumerate(zip(a_lines, b_lines, strict=False)):
        if la != lb:
            return f"line {i + 1}: baseline={la!r} current={lb!r}"
    if len(a_lines) != len(b_lines):
        return f"line count: baseline={len(a_lines)} current={len(b_lines)}"
    return None


def parse_routing_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    in_rows = False
    for line in text.splitlines():
        if line == ROUTING_HEADER:
            in_rows = True
            continue
        if not in_rows:
            continue
        if not line.strip() or line.startswith("-") or line.startswith("="):
            in_rows = False
            continue
        if "|" not in line:
            continue
        action, rest = line.split("|", 1)
        rows[action] = rest
    return rows


def extract_block(text: str, header: str) -> str:
    marker = f"{header}\n" + "-" * 72 + "\n"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    return text[start:].strip()


def compare_rows(baseline: dict[str, str], current: dict[str, str]) -> list[RowResult]:
    all_actions = sorted(set(baseline) | set(current))
    results: list[RowResult] = []
    for action in all_actions:
        base = baseline.get(action, "<missing>")
        curr = current.get(action, "<missing>")
        match = base == curr
        diff = None if match else first_diff(base, curr)
        results.append(
            RowResult(
                action=action,
                baseline=base,
                current=curr,
                match=match,
                first_diff_line=diff,
            )
        )
    return results


def compare_block(name: str, baseline: str, current: str) -> BlockResult:
    match = baseline == current
    return BlockResult(
        name=name,
        baseline_hash=sha256(baseline),
        current_hash=sha256(current),
        baseline_chars=len(baseline),
        current_chars=len(current),
        match=match,
        first_diff_line=None if match else first_diff(baseline, current),
    )


def run_inspect() -> str:
    if not INSPECT_SCRIPT.is_file():
        raise FileNotFoundError(f"Missing inspect script: {INSPECT_SCRIPT}")
    proc = subprocess.run(
        [sys.executable, str(INSPECT_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"inspect_prompt_routing.py failed (exit {proc.returncode}):\n"
            f"{proc.stderr or proc.stdout}"
        )
    return proc.stdout


def write_report(
    row_results: list[RowResult],
    block_results: list[BlockResult],
    *,
    baseline_path: Path,
    legacy_commit: str,
) -> None:
    row_passed = sum(1 for r in row_results if r.match)
    row_failed = len(row_results) - row_passed
    block_passed = sum(1 for r in block_results if r.match)
    block_failed = len(block_results) - block_passed
    overall = row_failed == 0 and block_failed == 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "PROMPT ROUTING PARITY REPORT",
        "=" * 72,
        f"Generated:        {now}",
        f"Legacy baseline:    {baseline_path}",
        f"Legacy commit:      {legacy_commit}",
        f"Inspect script:     {INSPECT_SCRIPT.relative_to(REPO_ROOT)}",
        "",
        f"OVERALL:            {'PASS' if overall else 'FAIL'}  "
        f"(rows {row_passed}/{len(row_results)}, "
        f"blocks {block_passed}/{len(block_results)})",
        "",
        "ROUTING ROW DETAILS",
        "-" * 72,
    ]

    for r in row_results:
        status = "PASS" if r.match else "FAIL"
        lines.append(f"[{status}] {r.action}")
        lines.append(f"       baseline: {r.baseline}")
        lines.append(f"       current:  {r.current}")
        if r.first_diff_line:
            lines.append(f"       first diff: {r.first_diff_line}")
        lines.append("")

    lines.extend(["PROMPT BODY BLOCKS", "-" * 72])
    for b in block_results:
        status = "PASS" if b.match else "FAIL"
        lines.append(f"[{status}] {b.name}")
        lines.append(f"       baseline sha256: {b.baseline_hash}")
        lines.append(f"       current  sha256: {b.current_hash}")
        lines.append(
            f"       chars: baseline={b.baseline_chars:,}  current={b.current_chars:,}"
        )
        if b.first_diff_line:
            lines.append(f"       first diff: {b.first_diff_line}")
        lines.append("")

    if overall:
        lines.append("All routing rows and prompt bodies match legacy 66e567c.")
    else:
        lines.append("MISMATCH — see FAIL rows/blocks above.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not BASELINE_PATH.is_file():
        print(
            f"ERROR: missing baseline at {BASELINE_PATH}\n"
            f"Capture from legacy commit {LEGACY_COMMIT} first.",
            file=sys.stderr,
        )
        return 1

    baseline_text = BASELINE_PATH.read_text(encoding="utf-8")
    current_text = run_inspect()

    row_results = compare_rows(
        parse_routing_rows(baseline_text),
        parse_routing_rows(current_text),
    )
    block_results = [
        compare_block(
            AE_BODIES_HEADER,
            extract_block(baseline_text, AE_BODIES_HEADER),
            extract_block(current_text, AE_BODIES_HEADER),
        ),
        compare_block(
            GUARDIAN_BODIES_HEADER,
            extract_block(baseline_text, GUARDIAN_BODIES_HEADER),
            extract_block(current_text, GUARDIAN_BODIES_HEADER),
        ),
    ]

    write_report(
        row_results,
        block_results,
        baseline_path=BASELINE_PATH,
        legacy_commit=LEGACY_COMMIT,
    )

    row_failed = [r for r in row_results if not r.match]
    block_failed = [b for b in block_results if not b.match]
    print(f"Wrote report: {REPORT_PATH}")
    print(
        f"Rows: {len(row_results) - len(row_failed)} passed, "
        f"{len(row_failed)} failed (of {len(row_results)})"
    )
    for r in row_results:
        if not r.match:
            print(f"  ✗ {r.action}: {r.first_diff_line or 'mismatch'}")

    for b in block_results:
        mark = "✓" if b.match else "✗"
        print(f"  {mark} {b.name}")
        if not b.match and b.first_diff_line:
            print(f"      {b.first_diff_line}")

    return 0 if not row_failed and not block_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
