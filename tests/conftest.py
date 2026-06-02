"""Shared pytest defaults for substrate tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _default_test_core_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tests that construct core runtime directly still declare bundles."""

    if "INTENTFRAME_CORE_CONFIG" not in os.environ:
        core_config = tmp_path / "core.yaml"
        core_config.write_text(
            "bundles:\n"
            "  - intentframe_native_kit.intentframe_native_bundles\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("INTENTFRAME_CORE_CONFIG", str(core_config))
