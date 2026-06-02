"""Configuration for the intentframe-core process.

The core process is a plugin host, just like the executor. Its action bundles
are declared in a core profile selected by ``INTENTFRAME_CORE_CONFIG``. The
supervisor only forwards environment; it does not know what bundles are.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_VALID_EXECUTOR_MODES = {"real", "dry_run"}
_DEFAULT_EXECUTOR_SOCKET = "~/.intentframe/run/executor.sock"


class CoreConfigurationError(RuntimeError):
    """Raised when intentframe-core has no usable runtime profile."""


class CoreExecutorConfig(BaseModel):
    """Executor client selection for intentframe-core."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(
        default="real",
        description="Executor mode: real or dry_run.",
    )
    socket_path: str = Field(
        default=_DEFAULT_EXECUTOR_SOCKET,
        description="UDS path for the real executor service.",
    )
    dry_run_context: str | None = Field(
        default=None,
        description="Optional dry-run context label, e.g. root for root-demo tests.",
    )


class CoreRuntimeConfig(BaseModel):
    """Non-plugin runtime knobs for intentframe-core."""

    model_config = ConfigDict(extra="forbid")

    verbose: bool = True
    skip_onboarding: bool = False


class CoreConfig(BaseModel):
    """Top-level intentframe-core profile."""

    model_config = ConfigDict(extra="forbid")

    bundles: list[str] = Field(
        default_factory=list,
        description=(
            "Action bundle refs to load at startup. Each entry is either an "
            "entry-point short name from 'intentframe.bundles' or an importable "
            "module path exposing register_bundles(registry)."
        ),
    )
    executor: CoreExecutorConfig = Field(default_factory=CoreExecutorConfig)
    runtime: CoreRuntimeConfig = Field(default_factory=CoreRuntimeConfig)
    bundle_options: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Opaque config slices owned by action bundle packages.",
    )


def load_core_config(
    config_path: str | Path | None = None,
    *,
    config_dict: dict[str, Any] | None = None,
) -> CoreConfig:
    """Load and validate the core profile, then overlay legacy env knobs.

    Resolution order:
        1. Explicit ``config_dict`` (tests).
        2. Explicit ``config_path``.
        3. ``INTENTFRAME_CORE_CONFIG``.

    There is deliberately no native-kit fallback. A deployment must declare
    which bundles intentframe-core loads.
    """

    if config_dict is not None:
        raw = config_dict
    else:
        path = Path(config_path) if config_path else _env_core_config_path()
        if path is not None:
            raw = _load_yaml(path)
        else:
            raise CoreConfigurationError(
                "No intentframe-core profile configured. Set "
                "INTENTFRAME_CORE_CONFIG to a core.yaml containing `bundles:`."
            )

    try:
        config = CoreConfig.model_validate(raw)
    except ValidationError as exc:
        raise CoreConfigurationError(
            f"Invalid intentframe-core configuration: {exc.error_count()} validation errors",
        ) from exc

    _overlay_legacy_env(config)
    _validate_core_config(config)
    return config


def _env_core_config_path() -> Path | None:
    value = os.environ.get("INTENTFRAME_CORE_CONFIG")
    return Path(value) if value else None


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CoreConfigurationError(f"Core config not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise CoreConfigurationError(f"Invalid YAML in core config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CoreConfigurationError(f"Core config must be a YAML mapping: {path}")
    return data


def _overlay_legacy_env(config: CoreConfig) -> None:
    """Keep existing launch scripts working while core.yaml becomes canonical."""

    if mode := os.environ.get("INTENTFRAME_EXECUTOR_MODE"):
        config.executor.mode = mode.strip().lower()
    if socket := os.environ.get("INTENTFRAME_EXECUTOR_SOCKET"):
        config.executor.socket_path = socket
    if context := os.environ.get("INTENTFRAME_DRY_RUN_CONTEXT"):
        config.executor.dry_run_context = context
    if verbose := os.environ.get("INTENTFRAME_VERBOSE"):
        config.runtime.verbose = verbose == "1"
    if skip := os.environ.get("INTENTFRAME_SKIP_ONBOARDING"):
        config.runtime.skip_onboarding = skip == "1"


def _validate_core_config(config: CoreConfig) -> None:
    if not config.bundles:
        raise CoreConfigurationError(
            "Core config must declare at least one action bundle under `bundles:`."
        )
    if config.executor.mode not in _VALID_EXECUTOR_MODES:
        expected = ", ".join(sorted(_VALID_EXECUTOR_MODES))
        raise CoreConfigurationError(
            f"Unknown core executor mode: {config.executor.mode!r}. Expected one of: {expected}."
        )


__all__ = [
    "CoreConfig",
    "CoreConfigurationError",
    "CoreExecutorConfig",
    "CoreRuntimeConfig",
    "load_core_config",
]
