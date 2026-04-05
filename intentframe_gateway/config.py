"""Gateway configuration — socket paths, feature flags, defaults."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _default_run_dir() -> Path:
    return Path(os.path.expanduser("~/.intentframe/run"))


def _default_data_dir() -> Path:
    return Path(os.path.expanduser("~/.intentframe/data"))


def _default_log_dir() -> Path:
    return Path(os.path.expanduser("~/.intentframe/logs"))


class BackendSocket(BaseModel):
    """Socket configuration for a single backend service."""
    name: str
    socket_name: str
    prefix: str
    health_path: str = "/health"


class GatewayConfig(BaseModel):
    """Top-level gateway configuration."""
    run_dir: Path = Field(default_factory=_default_run_dir)
    data_dir: Path = Field(default_factory=_default_data_dir)
    log_dir: Path = Field(default_factory=_default_log_dir)
    health_poll_interval: float = 5.0
    db_name: str = "gateway.db"

    vault_socket_name: str = "credential-vault.sock"

    backends: list[BackendSocket] = Field(default_factory=lambda: [
        BackendSocket(name="jarvis", socket_name="jarvis.sock", prefix="/jarvis"),
        BackendSocket(name="policy-registry", socket_name="policy-registry.sock", prefix="/policies"),
        BackendSocket(name="credential-vault", socket_name="credential-vault.sock", prefix="/vault"),
    ])

    platform_socket_name: str = "platform.sock"

    infra_sockets: list[BackendSocket] = Field(default_factory=lambda: [
        BackendSocket(name="resource-registry", socket_name="resource-registry.sock", prefix=""),
        BackendSocket(name="intentframe-core", socket_name="intentframe.sock", prefix=""),
        BackendSocket(name="executor", socket_name="executor.sock", prefix=""),
        BackendSocket(name="platform-server", socket_name="platform.sock", prefix=""),
    ])

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_name

    def socket_path(self, socket_name: str) -> Path:
        return self.run_dir / socket_name

    def all_service_names(self) -> list[str]:
        return [b.name for b in self.backends] + [b.name for b in self.infra_sockets]


def load_gateway_config() -> GatewayConfig:
    config = GatewayConfig()

    run_dir = os.environ.get("INTENTFRAME_RUN_DIR")
    if run_dir:
        config.run_dir = Path(run_dir)

    data_dir = os.environ.get("INTENTFRAME_DATA_DIR")
    if data_dir:
        config.data_dir = Path(data_dir)

    log_dir = os.environ.get("INTENTFRAME_LOG_DIR")
    if log_dir:
        config.log_dir = Path(log_dir)

    return config
