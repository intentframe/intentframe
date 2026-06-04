"""IntentFrame Edge — network-facing HTTP/TLS front door for a runtime.

The edge is a thin, stateless reverse proxy that terminates the network
(TCP / TLS / optional bearer auth) and forwards requests to the
supervisor-managed services over their Unix domain sockets. The default
backend set is minimal:

    /policies*                      → policy-registry.sock
    /handshake, /process, /audit*   → intentframe.sock

The optional ``/workspaces* → resource-registry.sock`` route is added by the
first-party kit profile (kit `edge_profile.yaml` in the installed package), selected
via ``INTENTFRAME_EDGE_CONFIG`` / ``--config``. This mirrors the supervisor's
registry-less default + opt-in kit profile.

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
