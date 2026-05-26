#!/usr/bin/env python3
"""
Onboarding prompt parity verifier — content-based checks.

System prompt:
  - common top substring
  - each bundle section substring (order-independent)
  - common bottom substring

User prompt:
  - full byte compare against frozen fixture

Usage:
    .venv/bin/python tests/verify_onboarding_prompts_parity.py

Fixtures (capture with inspect --write-baseline):
    tests/fixtures/onboarding/system_common_top.txt
    tests/fixtures/onboarding/system_common_bottom.txt
    tests/fixtures/onboarding/bundle_sections/<bundle_id>.txt
    tests/fixtures/onboarding/user_prompt.txt

Exit code 0 when all checks pass; 1 on any mismatch.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.inspect_onboarding_prompts import (  # noqa: E402
    build_jarvis_capabilities,
    build_jarvis_user_context,
    build_onboarding_prompts,
)
from tests.onboarding_prompt_parity import (  # noqa: E402
    FIXTURES_DIR,
    SYSTEM_COMMON_BOTTOM_PATH,
    SYSTEM_COMMON_TOP_PATH,
    USER_PROMPT_PATH,
    load_bundle_section_fixtures,
)

REPORT_PATH = FIXTURES_DIR / "parity_report.txt"


@dataclass(frozen=True)
class CheckResult:
    name: str
    match: bool
    detail: str | None = None


def verify_system_common_top(system_prompt: str, expected: str) -> CheckResult:
    if expected in system_prompt:
        return CheckResult("system common top", True)
    return CheckResult(
        "system common top",
        False,
        "expected common top substring missing from system prompt",
    )


def verify_system_common_bottom(system_prompt: str, expected: str) -> CheckResult:
    if expected in system_prompt:
        return CheckResult("system common bottom", True)
    return CheckResult(
        "system common bottom",
        False,
        "expected common bottom substring missing from system prompt",
    )


def verify_bundle_section(
    system_prompt: str,
    bundle_id: str,
    expected: str,
) -> CheckResult:
    name = f"bundle section: {bundle_id}"
    if expected in system_prompt:
        return CheckResult(name, True)
    return CheckResult(
        name,
        False,
        f"expected section for {bundle_id!r} missing from system prompt",
    )


def verify_user_prompt(user_prompt: str, expected: str) -> CheckResult:
    if user_prompt == expected:
        return CheckResult("user prompt (full)", True)
    return CheckResult(
        "user prompt (full)",
        False,
        f"byte mismatch (baseline={len(expected):,} current={len(user_prompt):,} chars)",
    )


async def run_checks() -> list[CheckResult]:
    if not SYSTEM_COMMON_TOP_PATH.is_file():
        raise FileNotFoundError(
            f"missing {SYSTEM_COMMON_TOP_PATH.relative_to(REPO_ROOT)} — "
            "run: .venv/bin/python tests/inspect_onboarding_prompts.py --write-baseline"
        )

    user_context = build_jarvis_user_context()
    capabilities = build_jarvis_capabilities()
    system_prompt, user_prompt = await build_onboarding_prompts(
        user_context=user_context,
        capabilities=capabilities,
    )

    common_top = SYSTEM_COMMON_TOP_PATH.read_text(encoding="utf-8")
    common_bottom = SYSTEM_COMMON_BOTTOM_PATH.read_text(encoding="utf-8")
    user_expected = USER_PROMPT_PATH.read_text(encoding="utf-8")
    bundle_sections = load_bundle_section_fixtures()

    results = [
        verify_system_common_top(system_prompt, common_top),
        *(
            verify_bundle_section(system_prompt, bundle_id, text)
            for bundle_id, text in sorted(bundle_sections.items())
        ),
        verify_system_common_bottom(system_prompt, common_bottom),
        verify_user_prompt(user_prompt, user_expected),
    ]
    return results


def write_report(results: list[CheckResult]) -> None:
    passed = sum(1 for r in results if r.match)
    failed = len(results) - passed
    overall = failed == 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "ONBOARDING PROMPTS PARITY REPORT",
        "=" * 72,
        f"Generated:     {now}",
        f"Fixtures dir:  {FIXTURES_DIR.relative_to(REPO_ROOT)}",
        "",
        "Strategy:",
        "  - system: common top + bundle section substrings + common bottom",
        "  - user:   full byte compare",
        "  - bundle section order is NOT compared",
        "",
        f"OVERALL:       {'PASS' if overall else 'FAIL'}  "
        f"({passed}/{len(results)} checks passed)",
        "",
        "CHECK DETAILS",
        "-" * 72,
    ]

    for result in results:
        status = "PASS" if result.match else "FAIL"
        lines.append(f"[{status}] {result.name}")
        if result.detail:
            lines.append(f"       {result.detail}")
        lines.append("")

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    try:
        results = await run_checks()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    write_report(results)

    passed = sum(1 for r in results if r.match)
    failed = len(results) - passed
    print(f"Wrote report: {REPORT_PATH}")
    print(f"Checks: {passed} passed, {failed} failed (of {len(results)})")

    for result in results:
        mark = "✓" if result.match else "✗"
        print(f"  {mark} {result.name}")
        if result.detail and not result.match:
            print(f"      {result.detail}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import asyncio as _asyncio
    raise SystemExit(_asyncio.run(main()))
