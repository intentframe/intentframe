"""Shared helpers for onboarding prompt inspect + parity verification."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "onboarding"
SYSTEM_COMMON_TOP_PATH = FIXTURES_DIR / "system_common_top.txt"
SYSTEM_COMMON_BOTTOM_PATH = FIXTURES_DIR / "system_common_bottom.txt"
BUNDLE_SECTIONS_DIR = FIXTURES_DIR / "bundle_sections"
USER_PROMPT_PATH = FIXTURES_DIR / "user_prompt.txt"


def bundle_section_sources() -> dict[str, str]:
    """Action-family middle blocks (future ``ActionBundle.onboarding_guardrails``)."""
    from intentframe_native_bundles.onboarding.guardrail_sections import (
        data_modification_section,
        email_section,
        file_access_section,
        financial_section,
        terminal_section,
        user_interaction_section,
    )

    return {
        "api": financial_section(),
        "file_access": file_access_section(),
        "user_io": user_interaction_section(),
        "terminal": terminal_section(),
        "data_modification": data_modification_section(),
        "email": email_section(),
    }


def split_system_prompt(system_prompt: str) -> tuple[str, str, str]:
    """Return ``(common_top, middle, common_bottom)`` from a full system prompt."""
    middle = "\n\n".join(bundle_section_sources().values())
    if middle not in system_prompt:
        raise ValueError("bundle middle sections not found in system prompt")
    top, bottom = system_prompt.split(middle, 1)
    return top, middle, bottom


def load_bundle_section_fixtures() -> dict[str, str]:
    """Load frozen per-bundle section fixtures keyed by bundle id."""
    if not BUNDLE_SECTIONS_DIR.is_dir():
        raise FileNotFoundError(f"missing bundle section fixtures: {BUNDLE_SECTIONS_DIR}")
    fixtures: dict[str, str] = {}
    for path in sorted(BUNDLE_SECTIONS_DIR.glob("*.txt")):
        fixtures[path.stem] = path.read_text(encoding="utf-8")
    if not fixtures:
        raise FileNotFoundError(f"no bundle section fixtures in {BUNDLE_SECTIONS_DIR}")
    return fixtures


def write_parity_fixtures(*, system_prompt: str, user_prompt: str) -> None:
    """Write split onboarding parity fixtures."""
    top, _middle, bottom = split_system_prompt(system_prompt)
    sections = bundle_section_sources()

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_SECTIONS_DIR.mkdir(parents=True, exist_ok=True)

    SYSTEM_COMMON_TOP_PATH.write_text(top, encoding="utf-8")
    SYSTEM_COMMON_BOTTOM_PATH.write_text(bottom, encoding="utf-8")
    USER_PROMPT_PATH.write_text(user_prompt, encoding="utf-8")

    for bundle_id, text in sections.items():
        (BUNDLE_SECTIONS_DIR / f"{bundle_id}.txt").write_text(text, encoding="utf-8")
