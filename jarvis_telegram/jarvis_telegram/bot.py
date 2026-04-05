"""Jarvis Telegram bot — entry point and application wiring.

Starts a long-polling Telegram bot that:
  1. Waits for the Jarvis API server to be healthy.
  2. Registers chat and command handlers.
  3. Listens on /events WebSocket for proactive heartbeat alerts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from loguru import logger
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from jarvis_telegram.client import JarvisClient
from jarvis_telegram.config import TelegramConfig, load_config
from jarvis_telegram.handlers import handle_chat, handle_help, handle_start, handle_status


# ---------------------------------------------------------------------------
# Server readiness
# ---------------------------------------------------------------------------

_STARTUP_TIMEOUT = 180  # seconds


class JarvisServerNotReady(RuntimeError):
    """Raised when the Jarvis API server doesn't become healthy in time."""


async def _wait_for_server(client: JarvisClient) -> bool:
    """Poll the Jarvis server until it responds to /health or timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _STARTUP_TIMEOUT
    interval = 1.0
    while loop.time() < deadline:
        if await client.is_healthy():
            return True
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 5.0)
    return False


# ---------------------------------------------------------------------------
# Proactive event listener (heartbeat alerts)
# ---------------------------------------------------------------------------

async def _event_listener(socket_path: str, chat_id: int, app: Application) -> None:
    """Connect to the Jarvis /events WebSocket and forward alerts to Telegram."""
    from websockets.asyncio.client import connect

    uri = "ws://jarvis-local/events"

    while True:
        try:
            async with connect(uri, unix=True, path=socket_path) as ws:
                logger.info("Connected to /events WebSocket")
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "heartbeat_alert":
                        message = event.get("message", "")
                        if message:
                            try:
                                await app.bot.send_message(
                                    chat_id=chat_id,
                                    text=f"[Alert]\n\n{message}",
                                )
                            except Exception as exc:
                                logger.warning(f"Failed to send heartbeat alert: {exc}")
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(f"/events WebSocket disconnected: {exc}, reconnecting in 5s")
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Post-init callback — start event listener after bot is running
# ---------------------------------------------------------------------------

async def _post_init(app: Application) -> None:
    config: TelegramConfig = app.bot_data["config"]
    client: JarvisClient = app.bot_data["jarvis_client"]

    bot_info = await app.bot.get_me()
    logger.info(f"Connected to Telegram bot: @{bot_info.username} (id={bot_info.id})")

    logger.info("Waiting for Jarvis server to be ready\u2026")
    if not await _wait_for_server(client):
        raise JarvisServerNotReady(
            f"Jarvis server did not become ready within {_STARTUP_TIMEOUT}s"
        )
    logger.info("Jarvis server is ready")

    app.bot_data["event_task"] = asyncio.create_task(
        _event_listener(config.jarvis_socket_path, config.allowed_user_id, app)
    )

    logger.info("Bot is live — polling for updates")


async def _post_shutdown(app: Application) -> None:
    logger.info("Shutting down\u2026")

    task = app.bot_data.get("event_task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Event listener stopped")

    client: JarvisClient | None = app.bot_data.get("jarvis_client")
    if client:
        await client.close()
        logger.info("Jarvis client closed")

    logger.info("Telegram bot shut down")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def build_app(config: TelegramConfig) -> Application:
    """Wire up the Telegram application with handlers and shared state."""
    jarvis_client = JarvisClient(config.jarvis_socket_path)

    app = (
        Application.builder()
        .token(config.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.bot_data["config"] = config
    app.bot_data["jarvis_client"] = jarvis_client
    app.bot_data["allowed_user_id"] = config.allowed_user_id
    app.bot_data["max_response_chars"] = config.max_response_chars

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat))

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Console script entry point: ``jarvis-telegram``."""
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    log_dir = Path("~/.jarvis/logs").expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_dir / "telegram.log"),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    )

    config = load_config()
    logger.info("Starting Jarvis Telegram bot")

    app = build_app(config)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
