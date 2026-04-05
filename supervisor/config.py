"""
Supervisor Configuration.

Defines the config schema for the supervisor: socket paths, startup order,
health check intervals, process resource limits, and logging.

Configuration sources (in priority order):
    1. CLI arguments
    2. Environment variables (INTENTFRAME_*)
    3. Config file (~/.intentframe/config.toml)
    4. Defaults
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


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

    services: list[ServiceConfig] = Field(default_factory=lambda: [
        ServiceConfig(
            name="policy-registry",
            module="policy_registry.server:app",
            socket_name="policy-registry.sock",
        ),
        ServiceConfig(
            name="resource-registry",
            module="resource_registry.server:app",
            socket_name="resource-registry.sock",
        ),
        ServiceConfig(
            name="executor",
            module="executor.server:app",
            socket_name="executor.sock",
        ),
        ServiceConfig(
            name="intentframe-core",
            module="intentframe_server.server:app",
            socket_name="intentframe.sock",
            depends_on=["policy-registry", "resource-registry", "executor"],
        ),
    ])

    def socket_path(self, service_name: str) -> Path:
        """Full path to a service's Unix Domain Socket."""
        for svc in self.services:
            if svc.name == service_name:
                return self.run_dir / svc.socket_name
        raise KeyError(f"Unknown service: {service_name}")


def load_supervisor_config() -> SupervisorConfig:
    """Load config from file / env / defaults."""
    config = SupervisorConfig()

    run_dir = os.environ.get("INTENTFRAME_RUN_DIR")
    if run_dir:
        config.run_dir = Path(run_dir)

    log_dir = os.environ.get("INTENTFRAME_LOG_DIR")
    if log_dir:
        config.log_dir = Path(log_dir)

    return config
