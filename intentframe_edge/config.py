"""Edge configuration — backends, run dir, listen address, TLS, auth.

Everything is env-overridable so the edge can be configured entirely
from a container environment (docker-compose, k8s) with no code change.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger("intentframe.edge")


def _default_run_dir() -> Path:
    return Path(
        os.environ.get(
            "INTENTFRAME_RUN_DIR",
            os.path.expanduser("~/.intentframe/run"),
        )
    )


class Backend(BaseModel):
    """A single upstream service reached over its UDS.

    ``prefixes`` are the HTTP path prefixes routed to this backend.  The
    edge matches the longest prefix first, so backends never collide.
    """

    name: str
    socket_name: str
    # Label used as the httpx base_url host (cosmetic; UDS ignores host).
    upstream_host: str
    prefixes: tuple[str, ...]


# The three services a remote test/agent client legitimately needs.
# Executor and credential-vault are intentionally absent — they stay
# UDS-only inside the environment.
DEFAULT_BACKENDS: list[Backend] = [
    Backend(
        name="policy-registry",
        socket_name="policy-registry.sock",
        upstream_host="policy-registry",
        prefixes=("/policies",),
    ),
    Backend(
        name="resource-registry",
        socket_name="resource-registry.sock",
        upstream_host="resource-registry",
        prefixes=("/workspaces",),
    ),
    Backend(
        name="intentframe-core",
        socket_name="intentframe.sock",
        upstream_host="intentframe",
        prefixes=("/handshake", "/process", "/audit"),
    ),
]


class EdgeConfig(BaseModel):
    """Top-level edge configuration."""

    run_dir: Path = Field(default_factory=_default_run_dir)
    host: str = "0.0.0.0"
    port: int = 8443

    # Optional shared bearer token. When set, every proxied request must
    # carry ``Authorization: Bearer <token>``. (mTLS is handled at the
    # TLS layer below; this is a coarse app-level gate on top of it.)
    auth_token: str | None = None

    # Optional TLS. When cert+key are set the edge serves HTTPS; adding
    # ca enables mutual TLS (client-cert required).
    tls_cert: str | None = None
    tls_key: str | None = None
    tls_ca: str | None = None

    backends: list[Backend] = Field(default_factory=lambda: list(DEFAULT_BACKENDS))

    def socket_path(self, backend: Backend) -> Path:
        return self.run_dir / backend.socket_name

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert and self.tls_key)

    @property
    def mtls_enabled(self) -> bool:
        return self.tls_enabled and bool(self.tls_ca)


def load_edge_config() -> EdgeConfig:
    """Build config from defaults overlaid with ``INTENTFRAME_EDGE_*`` env."""
    config = EdgeConfig()

    if run_dir := os.environ.get("INTENTFRAME_RUN_DIR"):
        config.run_dir = Path(run_dir)
    if host := os.environ.get("INTENTFRAME_EDGE_HOST"):
        config.host = host
    if port := os.environ.get("INTENTFRAME_EDGE_PORT"):
        config.port = int(port)

    config.auth_token = os.environ.get("INTENTFRAME_EDGE_TOKEN") or None
    config.tls_cert = os.environ.get("INTENTFRAME_EDGE_TLS_CERT") or None
    config.tls_key = os.environ.get("INTENTFRAME_EDGE_TLS_KEY") or None
    config.tls_ca = os.environ.get("INTENTFRAME_EDGE_TLS_CA") or None

    _warn_on_insecure_config(config)
    return config


def _warn_on_insecure_config(config: EdgeConfig) -> None:
    """Surface easy-to-miss misconfigurations as loud warnings."""
    # Partial TLS: exactly one of cert/key set silently disables TLS.
    if bool(config.tls_cert) != bool(config.tls_key):
        logger.warning(
            "Partial TLS config: both INTENTFRAME_EDGE_TLS_CERT and "
            "INTENTFRAME_EDGE_TLS_KEY are required — TLS will stay DISABLED "
            "(serving plain HTTP)."
        )
    # Bearer token over plaintext travels in the clear.
    if config.auth_token and not config.tls_enabled:
        logger.warning(
            "INTENTFRAME_EDGE_TOKEN is set but TLS is disabled — the bearer "
            "token will be sent in cleartext. Enable TLS for any real network."
        )
