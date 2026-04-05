"""Jarvis API Server — FastAPI application wrapping JarvisAgent.

Runs on UDS by default (/tmp/jarvis.sock), or TCP with ``--tcp``.
Provides /chat, /chat/stream, /session, /events endpoints
so any local client (Telegram bot, dashboard, CLI) can talk to Jarvis.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from jarvis.agent import JarvisAgent
from jarvis.config import load_config
from jarvis.server.events import EventBus
from jarvis.state import GatedJarvis


# ---------------------------------------------------------------------------
# Lifespan — owns JarvisAgent lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    jarvis = JarvisAgent(config)

    logger.info("Jarvis API server starting — running setup()…")
    await jarvis.setup()

    app.state.gated_jarvis = GatedJarvis(jarvis, config)

    event_bus = EventBus()
    app.state.event_bus = event_bus

    jarvis.heartbeat.set_event_callback(event_bus.publish)

    logger.info("Jarvis API server ready")
    try:
        yield
    finally:
        logger.info("Jarvis API server shutting down…")
        await jarvis.shutdown()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Jarvis API",
    version="0.1.0",
    lifespan=lifespan,
)

# Deferred import: routes imports from state/schemas which are already
# resolved, but this must stay below ``app = FastAPI(...)`` to avoid
# a circular reference if routes ever need to reference ``app``.
from jarvis.server.routes import router  # noqa: E402

app.include_router(router)


# ---------------------------------------------------------------------------
# Entry point — UDS by default, TCP with --tcp
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the Jarvis API server on UDS (default) or TCP (--tcp flag)."""
    import argparse
    import sys
    from pathlib import Path

    import uvicorn

    parser = argparse.ArgumentParser(description="Jarvis API server")
    parser.add_argument(
        "--tcp", action="store_true",
        help="Listen on TCP 127.0.0.1:8100 instead of UDS",
    )
    parser.add_argument(
        "--socket", default="/tmp/jarvis.sock",
        help="UDS path (default: /tmp/jarvis.sock)",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    if args.tcp:
        uvicorn.run("jarvis.server.app:app", host="127.0.0.1", port=8100, log_level="info")
    else:
        sock = Path(args.socket)
        if sock.exists():
            logger.info(f"Removing stale socket: {sock}")
            sock.unlink()
        uvicorn.run("jarvis.server.app:app", uds=args.socket, log_level="info")


if __name__ == "__main__":
    main()
