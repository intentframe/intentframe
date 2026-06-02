"""Tests for intentframe-core runtime profile loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from intentframe_server.config import CoreConfigurationError, load_core_config


def test_core_config_loads_bundles_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "core.yaml"
    path.write_text(
        "bundles:\n"
        "  - acme\n"
        "executor:\n"
        "  mode: real\n"
        "runtime:\n"
        "  verbose: false\n",
        encoding="utf-8",
    )

    config = load_core_config(path)

    assert config.bundles == ["acme"]
    assert config.executor.mode == "real"
    assert config.runtime.verbose is False


def test_core_config_fails_without_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTENTFRAME_CORE_CONFIG", raising=False)

    with pytest.raises(CoreConfigurationError, match="No intentframe-core profile"):
        load_core_config()


def test_core_config_legacy_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "core.yaml"
    path.write_text("bundles:\n  - acme\nexecutor:\n  mode: real\n", encoding="utf-8")
    monkeypatch.setenv("INTENTFRAME_EXECUTOR_MODE", "dry_run")
    monkeypatch.setenv("INTENTFRAME_SKIP_ONBOARDING", "1")

    config = load_core_config(path)

    assert config.executor.mode == "dry_run"
    assert config.runtime.skip_onboarding is True
