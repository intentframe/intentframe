"""Shared helpers for onboarding prompt inspect + parity verification."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "onboarding"
SYSTEM_COMMON_TOP_PATH = FIXTURES_DIR / "system_common_top.txt"
SYSTEM_COMMON_BOTTOM_PATH = FIXTURES_DIR / "system_common_bottom.txt"
BUNDLE_SECTIONS_DIR = FIXTURES_DIR / "bundle_sections"
USER_PROMPT_PATH = FIXTURES_DIR / "user_prompt.txt"


def _section_key(text: str, fallback: str) -> str:
    """Derive a filesystem-safe key from a section's ``### Heading`` line."""
    m = re.match(r"###\s+([^\n(]+)", text.strip())
    if m:
        return re.sub(r"[^a-z0-9]+", "_", m.group(1).strip().lower()).strip("_")
    return fallback


def bundle_section_sources(allowed_action_ids: frozenset[str]) -> dict[str, str]:
    """All middle-section blocks keyed by stable name.

    Bundle sections are keyed by ``bundle.bundle_id``.
    Manifest sections are keyed from their ``### Heading`` line.
    """
    from intentframe_bundle_sdk.registry import all_action_bundles, onboarding_manifest

    sections: dict[str, str] = {}
    for bundle in all_action_bundles():
        if not (bundle.action_ids & allowed_action_ids):
            continue
        text = bundle.onboarding_guardrails().strip()
        if text:
            sections[bundle.bundle_id] = text

    for i, section in enumerate(onboarding_manifest().sections):
        text = section.strip()
        if text:
            key = _section_key(text, f"manifest_{i}")
            sections[key] = text

    return sections


def split_system_prompt(
    system_prompt: str,
    allowed_action_ids: frozenset[str],
) -> tuple[str, str, str]:
    """Return ``(common_top, middle, common_bottom)`` from a full system prompt."""
    from intentframe_bundle_sdk.onboarding import render_onboarding_bundle_context

    middle = render_onboarding_bundle_context(allowed_action_ids)
    if middle not in system_prompt:
        raise ValueError("bundle middle sections not found in system prompt")
    top, bottom = system_prompt.split(middle, 1)
    return top, middle, bottom


def load_bundle_section_fixtures() -> dict[str, str]:
    """Load frozen per-section fixtures keyed by filename stem."""
    if not BUNDLE_SECTIONS_DIR.is_dir():
        raise FileNotFoundError(f"missing bundle section fixtures: {BUNDLE_SECTIONS_DIR}")
    fixtures: dict[str, str] = {}
    for path in sorted(BUNDLE_SECTIONS_DIR.glob("*.txt")):
        fixtures[path.stem] = path.read_text(encoding="utf-8")
    if not fixtures:
        raise FileNotFoundError(f"no bundle section fixtures in {BUNDLE_SECTIONS_DIR}")
    return fixtures


def write_parity_fixtures(
    *,
    system_prompt: str,
    user_prompt: str,
    allowed_action_ids: frozenset[str],
) -> None:
    """Write split onboarding parity fixtures."""
    top, _middle, bottom = split_system_prompt(system_prompt, allowed_action_ids)
    sections = bundle_section_sources(allowed_action_ids)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLE_SECTIONS_DIR.mkdir(parents=True, exist_ok=True)

    for stale in BUNDLE_SECTIONS_DIR.glob("*.txt"):
        stale.unlink()

    SYSTEM_COMMON_TOP_PATH.write_text(top, encoding="utf-8")
    SYSTEM_COMMON_BOTTOM_PATH.write_text(bottom, encoding="utf-8")
    USER_PROMPT_PATH.write_text(user_prompt, encoding="utf-8")

    for key, text in sections.items():
        (BUNDLE_SECTIONS_DIR / f"{key}.txt").write_text(text, encoding="utf-8")
