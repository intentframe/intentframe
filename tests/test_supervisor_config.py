from __future__ import annotations

import pytest

from supervisor.config import ServiceConfig, SupervisorConfig, load_supervisor_config
from supervisor.config import _apply_executor_mode, _executor_mode_from_env


def _service(config, name: str):
    return next((svc for svc in config.services if svc.name == name), None)


def test_supervisor_config_real_mode_starts_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTENTFRAME_EXECUTOR_MODE", raising=False)

    config = load_supervisor_config()

    assert _service(config, "executor") is not None
    core = _service(config, "intentframe-core")
    assert core is not None
    assert "executor" in core.depends_on


def test_supervisor_config_dry_run_omits_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTENTFRAME_EXECUTOR_MODE", "dry_run")

    config = load_supervisor_config()

    assert _service(config, "executor") is None
    core = _service(config, "intentframe-core")
    assert core is not None
    assert "executor" not in core.depends_on
    assert {"policy-registry", "resource-registry"} <= set(core.depends_on)


def test_supervisor_config_rejects_unknown_executor_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTENTFRAME_EXECUTOR_MODE", "dryrun")

    with pytest.raises(ValueError, match="Unknown INTENTFRAME_EXECUTOR_MODE"):
        load_supervisor_config()


def test_supervisor_config_rejects_blank_executor_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTENTFRAME_EXECUTOR_MODE", "")

    with pytest.raises(ValueError, match="Unknown INTENTFRAME_EXECUTOR_MODE"):
        load_supervisor_config()


def test_supervisor_config_executor_mode_trimmed_and_lowercased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTENTFRAME_EXECUTOR_MODE", "  DRY_RUN  ")

    assert _executor_mode_from_env() == "dry_run"


def test_apply_executor_mode_strips_executor_from_any_service() -> None:
    """Regression: dep stripping must not be hardcoded to intentframe-core."""
    config = SupervisorConfig(
        services=[
            ServiceConfig(
                name="policy-registry",
                module="policy_registry.server:app",
                socket_name="policy-registry.sock",
            ),
            ServiceConfig(
                name="executor",
                module="executor.server:app",
                socket_name="executor.sock",
            ),
            ServiceConfig(
                name="hypothetical-service",
                module="hypothetical.server:app",
                socket_name="hypothetical.sock",
                depends_on=["policy-registry", "executor"],
            ),
        ]
    )

    _apply_executor_mode(config, "dry_run")

    assert _service(config, "executor") is None
    hypothetical = _service(config, "hypothetical-service")
    assert hypothetical is not None
    assert "executor" not in hypothetical.depends_on
    assert "policy-registry" in hypothetical.depends_on


def test_apply_executor_mode_real_is_noop() -> None:
    config = SupervisorConfig()
    original_names = [svc.name for svc in config.services]

    _apply_executor_mode(config, "real")

    assert [svc.name for svc in config.services] == original_names
