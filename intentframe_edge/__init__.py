"""IntentFrame Edge — network-facing HTTP/TLS front door for a runtime.

The edge is a thin, stateless reverse proxy that terminates the network
(TCP / TLS / optional bearer auth) and forwards requests to the
supervisor-managed services over their Unix domain sockets:

    /policies*                      → policy-registry.sock
    /workspaces*                    → resource-registry.sock
    /handshake, /process, /audit*   → intentframe.sock

It deliberately does NOT expose the executor or the credential vault —
those stay UDS-only inside the environment.  The edge holds no state and
is not a "writer", so it does not affect the single-writer invariant; run
it as a sidecar next to the runtime, sharing the run-dir volume.

Run it with::

    python -m intentframe_edge
    # or, once installed:
    intentframe-edge
"""

from intentframe_edge.config import EdgeConfig, load_edge_config

__all__ = ["EdgeConfig", "load_edge_config"]
