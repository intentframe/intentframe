#!/usr/bin/env python3
"""
Deterministic hardened-prompt parity verifier.

Captures output from tests/inspect_hardened_prompts.py, normalizes random
per-request boundary tokens, and byte-compares each section against the
legacy baseline captured from commit ee04d7f.

Usage:
    .venv/bin/python tests/verify_hardened_prompts_parity.py

Artifacts:
    tests/fixtures/hardened_prompts_legacy_baseline.txt  — frozen legacy output
    tests/fixtures/hardened_prompts_parity_report.txt     — human-readable proof

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
INSPECT_SCRIPT = REPO_ROOT / "tests" / "inspect_hardened_prompts.py"
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "hardened_prompts_legacy_baseline.txt"
REPORT_PATH = REPO_ROOT / "tests" / "fixtures" / "hardened_prompts_parity_report.txt"
LEGACY_COMMIT = "ee04d7f"

SECTION_HEADER = re.compile(
    r"^═{72}\n  (?P<title>.+?)\n═{72}\n",
    re.MULTILINE,
)
BOUNDARY_TOKEN = re.compile(r"[0-9a-f]{32}_UNTRUSTED_(START|END)")
BOUNDARY_REMINDER = re.compile(
    r"REMINDER: Everything between [0-9a-f]{32}_UNTRUSTED_START "
    r"and [0-9a-f]{32}_UNTRUSTED_END"
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


def normalize_boundaries(text: str) -> str:
    """Strip non-deterministic per-request hex boundary tokens."""
    text = BOUNDARY_TOKEN.sub(r"<BOUNDARY>_UNTRUSTED_\1", text)
    text = BOUNDARY_REMINDER.sub(
        "REMINDER: Everything between <BOUNDARY>_UNTRUSTED_START "
        "and <BOUNDARY>_UNTRUSTED_END",
        text,
    )
    return text


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_sections(text: str) -> dict[str, str]:
    """Split inspect output into titled sections."""
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
            f"inspect_hardened_prompts.py failed (exit {proc.returncode}):\n"
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
        base_norm = normalize_boundaries(base_raw)
        curr_norm = normalize_boundaries(curr_raw)
        match = base_norm == curr_norm
        diff = None if match else first_diff(base_norm, curr_norm)
        results.append(
            SectionResult(
                title=title,
                baseline_hash=sha256(base_norm),
                current_hash=sha256(curr_norm),
                baseline_chars=len(base_norm),
                current_chars=len(curr_norm),
                match=match,
                first_diff_line=diff,
            )
        )
    return results


def write_report(
    results: list[SectionResult],
    *,
    baseline_path: Path,
    legacy_commit: str,
) -> None:
    passed = sum(1 for r in results if r.match)
    failed = len(results) - passed
    overall = failed == 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "HARDENED PROMPTS PARITY REPORT",
        "=" * 72,
        f"Generated:        {now}",
        f"Legacy baseline:    {baseline_path}",
        f"Legacy commit:      {legacy_commit}",
        f"Inspect script:     {INSPECT_SCRIPT.relative_to(REPO_ROOT)}",
        f"Normalization:      32-hex boundary tokens → <BOUNDARY>_UNTRUSTED_*",
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
        lines.append("All sections match after boundary-token normalization.")
        lines.append("Prompt content parity with legacy ee04d7f is VERIFIED.")
    else:
        lines.append("MISMATCH — see FAIL sections above.")

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

    baseline_sections = parse_sections(normalize_boundaries(baseline_text))
    current_sections = parse_sections(normalize_boundaries(current_text))
    results = compare_sections(baseline_sections, current_sections)

    write_report(results, baseline_path=BASELINE_PATH, legacy_commit=LEGACY_COMMIT)

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
