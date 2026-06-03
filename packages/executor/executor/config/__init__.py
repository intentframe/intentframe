"""
Configuration loading and validation for the IntentFrame Executor.

The executor is fully config-driven. A single executor.yaml file
determines which transport, auth verifier, credential backend,
and adapter set to load at startup.

No code changes needed to switch deployment profiles.
Just change the config file.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from executor.config.schema import ExecutorConfig
from executor_sdk.constants import DEFAULT_CONFIG_FILENAME
from executor_sdk.exceptions import ConfigurationError

__all__ = ["ExecutorConfig", "load_config"]


def load_config(
    config_path: str | Path | None = None,
    config_dict: dict | None = None,
) -> ExecutorConfig:
    """Load and validate executor configuration.

    Accepts either a file path to a YAML config or a pre-loaded dict.
    The config is validated against the Pydantic schema and returned
    as a typed ExecutorConfig object.

    Args:
        config_path: Path to executor.yaml. If None and config_dict is None,
                     searches default locations.
        config_dict: Pre-loaded config dict (e.g., from tests). Takes
                     priority over config_path if both are provided.

    Returns:
        Validated ExecutorConfig.

    Raises:
        ConfigurationError: If the config file is missing, unreadable,
                            or fails schema validation.
    """
    if config_dict is not None:
        raw = config_dict
    elif config_path is not None:
        raw = _load_yaml(Path(config_path))
    else:
        raw = _load_yaml(_find_default_config())

    try:
        return ExecutorConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Invalid executor configuration: {exc.error_count()} validation errors",
            details={"errors": exc.errors()},
        ) from exc


def _load_yaml(path: Path) -> dict:
    """Load a YAML file and return as dict."""
    if not path.exists():
        raise ConfigurationError(f"Config file not found: {path}")

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigurationError(f"Config file must be a YAML mapping: {path}")

    return data


def _find_default_config() -> Path:
    """Search for executor.yaml in default locations.

    Search order:
        1. Current working directory
        2. executor/config/ (relative to package)
        3. ~/.config/intentframe/

    Returns the first path that exists.
    Raises ConfigurationError if none found.
    """
    candidates = [
        Path.cwd() / DEFAULT_CONFIG_FILENAME,
        Path(__file__).parent / DEFAULT_CONFIG_FILENAME,
        Path.home() / ".config" / "intentframe" / DEFAULT_CONFIG_FILENAME,
    ]

    for path in candidates:
        if path.exists():
            return path

    locations = "\n  ".join(str(p) for p in candidates)
    raise ConfigurationError(
        f"No {DEFAULT_CONFIG_FILENAME} found. Searched:\n  {locations}"
    )
