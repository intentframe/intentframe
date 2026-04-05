"""Gateway process entry point.

This module provides the process-level entry point for starting
the gateway.  It is NOT a CLI frontend — the interactive CLI lives
in ``intentframe_cli``.

Entry point:
  - ``backend_main``  — native frontend entry (sets process group)
"""

from __future__ import annotations

import logging
import os
import sys


def _default_socket_path() -> str:
    run_dir = os.environ.get("INTENTFRAME_RUN_DIR", os.path.expanduser("~/.intentframe/run"))
    return os.path.join(run_dir, "gateway.sock")


def _run_gateway(socket_path: str | None = None) -> None:
    """Start the gateway uvicorn server (blocks until shutdown)."""
    import uvicorn

    frontend_mode = os.environ.get("INTENTFRAME_FRONTEND_MODE") == "1"
    uds = socket_path or _default_socket_path()
    os.makedirs(os.path.dirname(uds), exist_ok=True)

    log_stream = sys.stderr if frontend_mode else sys.stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=log_stream,
    )

    uvicorn.run(
        "intentframe_gateway.server:app",
        uds=uds,
        log_level="info",
        lifespan="on",
    )


def backend_main() -> None:
    """Entry point for a native frontend that spawns the gateway.

    Creates a new process group so the parent can kill the entire
    tree (gateway + supervisor + all children) with a single killpg().
    """
    os.setpgrp()
    os.environ.setdefault("INTENTFRAME_FRONTEND_MODE", "1")
    _run_gateway()


if __name__ == "__main__":
    _run_gateway()
