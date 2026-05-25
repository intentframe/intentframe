#!/usr/bin/env python3
"""
Deterministic onboarding-prompt parity verifier.

Captures output from tests/inspect_onboarding_prompts.py and byte-compares
each section against the frozen baseline.

Usage:
    .venv/bin/python tests/verify_onboarding_prompts_parity.py

Artifacts:
    tests/fixtures/onboarding_prompts_baseline.txt   — frozen inspect output
    tests/fixtures/onboarding_prompts_parity_report.txt — human-readable proof

Exit code 0 when every section matches; 1 on any mismatch.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSPECT_SCRIPT = REPO_ROOT / "tests" / "inspect_onboarding_prompts.py"
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "onboarding_prompts_baseline.txt"
REPORT_PATH = REPO_ROOT / "tests" / "fixtures" / "onboarding_prompts_parity_report.txt"

SECTION_HEADER = re.compile(
    r"^═{72}\n  (?P<title>.+?)\n═{72}\n",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SectionResult:
    title: str
    baseline_hash: str
    current_hash: str
    baseline_chars: int
    current_chars: int
    match: bool
    first_diff_line: str | None = None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(SECTION_HEADER.finditer(text))
    for idx, match in enumerate(matches):
        title = match.group("title").strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip("\n")
        sections[title] = body
    return sections


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
            f"inspect_onboarding_prompts.py failed (exit {proc.returncode}):\n"
            f"{proc.stderr or proc.stdout}"
        )
    return proc.stdout


def first_diff(a: str, b: str) -> str | None:
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    for i, (la, lb) in enumerate(zip(a_lines, b_lines, strict=False)):
        if la != lb:
            return f"line {i + 1}: baseline={la!r} current={lb!r}"
    if len(a_lines) != len(b_lines):
        return f"line count: baseline={len(a_lines)} current={len(b_lines)}"
    return None


def compare_sections(
    baseline_sections: dict[str, str],
    current_sections: dict[str, str],
) -> list[SectionResult]:
    all_titles = sorted(set(baseline_sections) | set(current_sections))
    results: list[SectionResult] = []

    for title in all_titles:
        base_raw = baseline_sections.get(title, "")
        curr_raw = current_sections.get(title, "")
        match = base_raw == curr_raw
        diff = None if match else first_diff(base_raw, curr_raw)
        results.append(
            SectionResult(
                title=title,
                baseline_hash=sha256(base_raw),
                current_hash=sha256(curr_raw),
                baseline_chars=len(base_raw),
                current_chars=len(curr_raw),
                match=match,
                first_diff_line=diff,
            )
        )
    return results


def write_report(results: list[SectionResult], *, baseline_path: Path) -> None:
    passed = sum(1 for r in results if r.match)
    failed = len(results) - passed
    overall = failed == 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "ONBOARDING PROMPTS PARITY REPORT",
        "=" * 72,
        f"Generated:        {now}",
        f"Baseline:           {baseline_path}",
        f"Inspect script:     {INSPECT_SCRIPT.relative_to(REPO_ROOT)}",
        "",
        f"OVERALL:            {'PASS' if overall else 'FAIL'}  "
        f"({passed}/{len(results)} sections match)",
        "",
        "SECTION DETAILS",
        "-" * 72,
    ]

    for r in results:
        status = "PASS" if r.match else "FAIL"
        lines.append(f"[{status}] {r.title}")
        lines.append(f"       baseline sha256: {r.baseline_hash}")
        lines.append(f"       current  sha256: {r.current_hash}")
        lines.append(
            f"       chars: baseline={r.baseline_chars:,}  current={r.current_chars:,}"
        )
        if r.first_diff_line:
            lines.append(f"       first diff: {r.first_diff_line}")
        lines.append("")

    if overall:
        lines.append("All sections match. Onboarding prompt parity is VERIFIED.")
    else:
        lines.append("MISMATCH — see FAIL sections above.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not BASELINE_PATH.is_file():
        print(
            f"ERROR: missing baseline at {BASELINE_PATH}\n"
            "Capture with: .venv/bin/python tests/inspect_onboarding_prompts.py --write-baseline",
            file=sys.stderr,
        )
        return 1

    baseline_text = BASELINE_PATH.read_text(encoding="utf-8")
    current_text = run_inspect()

    baseline_sections = parse_sections(baseline_text)
    current_sections = parse_sections(current_text)
    results = compare_sections(baseline_sections, current_sections)

    write_report(results, baseline_path=BASELINE_PATH)

    passed = sum(1 for r in results if r.match)
    failed = len(results) - passed
    print(f"Wrote report: {REPORT_PATH}")
    print(f"Sections: {passed} passed, {failed} failed (of {len(results)})")

    for r in results:
        mark = "✓" if r.match else "✗"
        print(f"  {mark} {r.title}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
