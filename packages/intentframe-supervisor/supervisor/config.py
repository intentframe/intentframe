"""
Supervisor Configuration.

Defines the config schema for the supervisor: socket paths, startup order,
health check intervals, process resource limits, and logging.

The service graph is admin-owned data, not supervisor logic: it is read from a
YAML file (``--config <path>`` on the CLI, falling back to the packaged default
``supervisor/config/supervisor.yaml``).  The packaged default is deliberately
dependency-free and EXCLUDES the resource-registry; first-party products opt
into the registry by pointing at the kit `supervisor_profile.yaml` (installed package path).

Configuration sources (in priority order):
    1. CLI arguments (``--config`` path)
    2. Packaged default config file (supervisor/config/supervisor.yaml)
    3. Environment variables (INTENTFRAME_RUN_DIR / INTENTFRAME_LOG_DIR /
       INTENTFRAME_EXECUTOR_MODE) overlaid on top
    4. In-code minimal default (resilient fallback if no file is found)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger("supervisor")

_VALID_EXECUTOR_MODES = {"real", "dry_run"}
_EXECUTOR_SERVICE_NAME = "executor"
_DEFAULT_CONFIG_FILENAME = "supervisor.yaml"


def _default_services() -> list[ServiceConfig]:
    """In-code minimal service graph (no resource-registry).

    Mirrors the packaged ``supervisor/config/supervisor.yaml`` so that direct
    ``SupervisorConfig()`` construction and the no-file fallback path both yield
    the same dependency-free default.
    """
    return [
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
            name="intentframe-server",
            module="intentframe_server.server:app",
            socket_name="intentframe.sock",
            depends_on=["policy-registry", "executor"],
        ),
    ]


def _default_run_dir() -> Path:
    return Path(os.path.expanduser("~/.intentframe/run"))


def _default_log_dir() -> Path:
    return Path(os.path.expanduser("~/.intentframe/logs"))


class ServiceConfig(BaseModel):
    """Configuration for a single service process."""
    name: str
    module: str                           # e.g. "policy_registry.server:app"
    socket_name: str                      # e.g. "policy-registry.sock"
    depends_on: list[str] = Field(default_factory=list)
    health_path: str = "/health"
    startup_timeout: float = 30.0         # seconds to wait for health
    restart_on_crash: bool = True
    max_restarts: int = 5


class SupervisorConfig(BaseModel):
    """Top-level supervisor configuration."""
    run_dir: Path = Field(default_factory=_default_run_dir)
    log_dir: Path = Field(default_factory=_default_log_dir)
    health_interval: float = 2.0          # seconds between health polls
    health_timeout: float = 5.0           # seconds per health request
    graceful_shutdown_timeout: float = 10.0

    services: list[ServiceConfig] = Field(default_factory=_default_services)

    def socket_path(self, service_name: str) -> Path:
        """Full path to a service's Unix Domain Socket."""
        for svc in self.services:
            if svc.name == service_name:
                return self.run_dir / svc.socket_name
        raise KeyError(f"Unknown service: {service_name}")


def _executor_mode_from_env() -> str:
    mode = os.environ.get("INTENTFRAME_EXECUTOR_MODE", "real").strip().lower()
    if mode not in _VALID_EXECUTOR_MODES:
        expected = ", ".join(sorted(_VALID_EXECUTOR_MODES))
        raise ValueError(
            f"Unknown INTENTFRAME_EXECUTOR_MODE: {mode!r}. Expected one of: {expected}."
        )
    return mode


def _apply_executor_mode(config: SupervisorConfig, mode: str) -> None:
    """Adjust the service graph for the selected runtime executor mode.

    ``real`` keeps the loaded service graph as-is.  ``dry_run`` makes
    intentframe-server use DryRunExecutor in-process, so the standalone
    executor service would be unused and is deliberately not started;
    we also strip ``executor`` from *every* service's ``depends_on`` so
    startup ordering stays valid and no future service silently waits
    on a dependency that was never started.
    """
    if mode == "real":
        return

    config.services = [
        svc for svc in config.services
        if svc.name != _EXECUTOR_SERVICE_NAME
    ]
    config.services = [
        svc.model_copy(
            update={
                "depends_on": [
                    dep for dep in svc.depends_on
                    if dep != _EXECUTOR_SERVICE_NAME
                ],
            }
        )
        if _EXECUTOR_SERVICE_NAME in svc.depends_on
        else svc
        for svc in config.services
    ]


def _packaged_default_config() -> Path:
    """Path to the supervisor's built-in default service graph YAML."""
    return Path(__file__).parent / "config" / _DEFAULT_CONFIG_FILENAME


def _load_config_file(path: Path) -> SupervisorConfig:
    """Validate a supervisor config YAML into a :class:`SupervisorConfig`."""
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Supervisor config must be a YAML mapping: {path}")
    return SupervisorConfig.model_validate(data)


def load_supervisor_config(
    config_path: str | Path | None = None,
) -> SupervisorConfig:
    """Load the supervisor config from a file path, env, and defaults.

    Resolution order for the service graph:
        1. ``config_path`` (from ``--config`` on the CLI), if given.
        2. The packaged default ``supervisor/config/supervisor.yaml``.
        3. The in-code minimal default (if no file is found on disk).

    ``run_dir`` / ``log_dir`` env overrides and the executor-mode adjustment
    are always overlaid on top of whichever graph was loaded.
    """
    path = Path(config_path) if config_path else _packaged_default_config()

    if path.exists():
        config = _load_config_file(path)
    elif config_path is not None:
        # An explicit path was requested but does not exist -- fail loudly
        # rather than silently falling back to a different service graph.
        raise FileNotFoundError(f"Supervisor config not found: {path}")
    else:
        logger.debug(
            "No supervisor config file at %s -- using in-code minimal default",
            path,
        )
        config = SupervisorConfig()

    run_dir = os.environ.get("INTENTFRAME_RUN_DIR")
    if run_dir:
        config.run_dir = Path(run_dir)

    log_dir = os.environ.get("INTENTFRAME_LOG_DIR")
    if log_dir:
        config.log_dir = Path(log_dir)

    _apply_executor_mode(config, _executor_mode_from_env())

    return config
