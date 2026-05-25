"""Bundle SDK ``render_onboarding_bundle_context`` tests."""

from __future__ import annotations

import pytest

from intentframe_bundle_sdk.onboarding import render_onboarding_bundle_context
from intentframe_bundle_sdk.registry import onboarding_manifest
from tests._bundle_loader import ensure_test_bundles_loaded


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_test_bundles_loaded()


def test_middle_includes_terminal_when_granted() -> None:
    middle = render_onboarding_bundle_context(frozenset({"RUN_COMMAND"}))
    assert "### Terminal (RUN_COMMAND)" in middle


def test_middle_omits_email_when_not_granted() -> None:
    middle = render_onboarding_bundle_context(frozenset({"RUN_COMMAND"}))
    assert "### Email Actions" not in middle


def test_manifest_file_access_always_present() -> None:
    """File access section from manifest always appears regardless of policy."""
    middle = render_onboarding_bundle_context(frozenset({"RUN_COMMAND"}))
    assert "### File Access:" in middle
    assert "Category1:" in middle
    assert "Category2:" in middle


def test_manifest_sections_verbatim() -> None:
    """Manifest sections are hardcoded verbatim strings."""
    sections = onboarding_manifest().sections
    assert len(sections) == 2
    assert "### File Access:" in sections[0]
    assert "IMPORTANT" in sections[0]
    assert "### Data Modification" in sections[1]
