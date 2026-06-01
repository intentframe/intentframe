"""Launch the IntentFrame edge with uvicorn (TCP, optional TLS/mTLS).

Configuration is env-driven (see ``intentframe_edge.config``); CLI flags
override host/port and select the backend profile for convenience::

    python -m intentframe_edge --host 0.0.0.0 --port 8443
    python -m intentframe_edge --config intentframe_native_kit/edge_profile.yaml
"""

from __future__ import annotations

import argparse
import os
import ssl

import uvicorn

from intentframe_edge.config import load_edge_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="intentframe-edge",
        description="IntentFrame network edge — HTTP/TLS front door that "
        "forwards to the runtime's UDS services.",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to an edge backend profile YAML. Defaults to the in-code "
            "minimal backends (policy-registry + intentframe-core). First-party "
            "products / test harnesses pass intentframe_native_kit/edge_profile.yaml "
            "to expose /workspaces. Equivalent to INTENTFRAME_EDGE_CONFIG."
        ),
    )
    args = parser.parse_args()

    # Set the env var before the app module is imported by uvicorn so the
    # ``app:app`` factory (which calls load_edge_config at import time) sees it.
    if args.config:
        os.environ["INTENTFRAME_EDGE_CONFIG"] = args.config

    config = load_edge_config()
    host = args.host or config.host
    port = args.port or config.port

    ssl_kwargs: dict = {}
    if config.tls_enabled:
        ssl_kwargs["ssl_certfile"] = config.tls_cert
        ssl_kwargs["ssl_keyfile"] = config.tls_key
        if config.mtls_enabled:
            ssl_kwargs["ssl_ca_certs"] = config.tls_ca
            ssl_kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED

    uvicorn.run(
        "intentframe_edge.app:app",
        host=host,
        port=port,
        log_level="info",
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
