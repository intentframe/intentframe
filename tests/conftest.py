"""Shared pytest defaults for substrate tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _default_test_core_bundles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that construct core runtime directly still declare bundles."""

    if (
        "INTENTFRAME_CORE_CONFIG" not in os.environ
        and "INTENTFRAME_BUNDLES" not in os.environ
    ):
        monkeypatch.setenv(
            "INTENTFRAME_BUNDLES",
            "intentframe_native_kit.intentframe_native_bundles",
        )
