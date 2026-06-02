from __future__ import annotations

from pathlib import Path

import intentframe_native_kit

from intentframe_gateway.profiles import resolve_core_config_path


def test_resolve_core_config_path_uses_override(monkeypatch) -> None:
    monkeypatch.setenv("INTENTFRAME_CORE_CONFIG", "/tmp/custom-core.yaml")

    assert resolve_core_config_path() == "/tmp/custom-core.yaml"


def test_resolve_core_config_path_falls_back_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("INTENTFRAME_CORE_CONFIG", raising=False)

    expected = Path(intentframe_native_kit.__file__).parent / "core.yaml"

    assert resolve_core_config_path() == str(expected)


def test_resolve_core_config_path_falls_back_when_empty(monkeypatch) -> None:
    monkeypatch.setenv("INTENTFRAME_CORE_CONFIG", "")

    expected = Path(intentframe_native_kit.__file__).parent / "core.yaml"

    assert resolve_core_config_path() == str(expected)
