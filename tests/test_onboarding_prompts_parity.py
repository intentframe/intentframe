"""Pytest wrapper for onboarding prompt parity checks."""

from __future__ import annotations

import asyncio

from tests.verify_onboarding_prompts_parity import run_checks


def test_onboarding_prompts_parity() -> None:
    results = asyncio.run(run_checks())
    failures = [r for r in results if not r.match]
    assert not failures, "\n".join(
        f"{r.name}: {r.detail or 'mismatch'}" for r in failures
    )
