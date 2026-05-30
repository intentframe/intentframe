"""Launch the IntentFrame edge with uvicorn (TCP, optional TLS/mTLS).

Configuration is env-driven (see ``intentframe_edge.config``); CLI flags
override host/port for convenience::

    python -m intentframe_edge --host 0.0.0.0 --port 8443
"""

from __future__ import annotations

import argparse
import ssl

import uvicorn

from intentframe_edge.config import load_edge_config


def main() -> None:
    config = load_edge_config()

    parser = argparse.ArgumentParser(
        prog="intentframe-edge",
        description="IntentFrame network edge — HTTP/TLS front door that "
        "forwards to the runtime's UDS services.",
    )
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port)
    args = parser.parse_args()

    ssl_kwargs: dict = {}
    if config.tls_enabled:
        ssl_kwargs["ssl_certfile"] = config.tls_cert
        ssl_kwargs["ssl_keyfile"] = config.tls_key
        if config.mtls_enabled:
            ssl_kwargs["ssl_ca_certs"] = config.tls_ca
            ssl_kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED

    uvicorn.run(
        "intentframe_edge.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
