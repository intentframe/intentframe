from __future__ import annotations

from pathlib import Path

import pytest

from intentframe_edge.config import EdgeConfig, _load_config_file, load_edge_config

import intentframe_native_kit

_KIT_PROFILE = (
    Path(intentframe_native_kit.__file__).resolve().parent
    / "edge_profile.yaml"
)


def _names(config: EdgeConfig) -> set[str]:
    return {b.name for b in config.backends}


def test_default_backends_exclude_resource_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edge's built-in default exposes only substrate services."""
    monkeypatch.delenv("INTENTFRAME_EDGE_CONFIG", raising=False)

    config = load_edge_config()

    assert _names(config) == {"policy-registry", "intentframe-server"}
    assert "resource-registry" not in _names(config)


def test_kit_profile_exposes_workspaces() -> None:
    """The first-party kit edge profile adds the resource-registry route."""
    config = _load_config_file(_KIT_PROFILE)

    assert "resource-registry" in _names(config)
    rr = next(b for b in config.backends if b.name == "resource-registry")
    assert "/workspaces" in rr.prefixes


def test_env_selects_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """INTENTFRAME_EDGE_CONFIG selects the backend profile."""
    monkeypatch.setenv("INTENTFRAME_EDGE_CONFIG", str(_KIT_PROFILE))

    config = load_edge_config()

    assert "resource-registry" in _names(config)


def test_env_network_overrides_apply_on_top(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network fields stay env-driven even when a profile is loaded."""
    monkeypatch.setenv("INTENTFRAME_EDGE_CONFIG", str(_KIT_PROFILE))
    monkeypatch.setenv("INTENTFRAME_EDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("INTENTFRAME_EDGE_PORT", "9000")

    config = load_edge_config()

    assert config.host == "127.0.0.1"
    assert config.port == 9000


def test_missing_explicit_config_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INTENTFRAME_EDGE_CONFIG", str(tmp_path / "nope.yaml"))

    with pytest.raises(FileNotFoundError):
        load_edge_config()
