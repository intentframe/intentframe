"""Telegram update handlers — chat messages and deterministic commands.

All handlers receive the ``JarvisClient`` and ``allowed_user_id`` via
``context.bot_data`` (set during application setup in ``bot.py``).
"""

from __future__ import annotations

import asyncio

from loguru import logger
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from jarvis_telegram.client import JarvisBusyError, JarvisClient, JarvisServerError, JarvisTimeoutError

_TELEGRAM_MSG_LIMIT = 4096
_THINKING_PLACEHOLDER = "Thinking\u2026"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(context: ContextTypes.DEFAULT_TYPE) -> JarvisClient:
    return context.bot_data["jarvis_client"]


def _allowed_user_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data["allowed_user_id"]


def _max_response_chars(context: ContextTypes.DEFAULT_TYPE) -> int:
    return context.bot_data.get("max_response_chars", 16_384)


def _is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return update.effective_user is not None and update.effective_user.id == _allowed_user_id(context)


async def _keep_typing(bot, chat_id: int, stop: asyncio.Event) -> None:
    """Re-send TYPING action every 4s until *stop* is set."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            pass


async def _send_response(
    thinking_msg, chat_id: int, bot, response: str, max_chars: int,
) -> None:
    """Edit the placeholder with *response*, splitting into follow-up messages if too long."""
    if not response:
        response = "(empty response)"

    if response == _THINKING_PLACEHOLDER:
        response = f"{response} "

    _TRUNCATION_SUFFIX = "\n\n\u2026 (truncated)"
    if len(response) > max_chars:
        response = response[: max_chars - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX

    if len(response) <= _TELEGRAM_MSG_LIMIT:
        await thinking_msg.edit_text(response)
        return

    chunks = [response[i:i + _TELEGRAM_MSG_LIMIT] for i in range(0, len(response), _TELEGRAM_MSG_LIMIT)]
    await thinking_msg.edit_text(chunks[0])
    _CONT_PREFIX = "(continued\u2026)\n\n"
    for chunk in chunks[1:]:
        await bot.send_message(chat_id=chat_id, text=_CONT_PREFIX + chunk)


# ---------------------------------------------------------------------------
# Chat handler — messages that go through the LLM
# ---------------------------------------------------------------------------

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a plain text message: thinking placeholder -> call Jarvis -> edit with response."""
    if not _is_authorized(update, context):
        user = update.effective_user
        logger.warning(f"Unauthorized message from user {user.id if user else '?'}")
        return
    if update.message is None or not update.message.text:
        return

    text = update.message.text
    chat_id = update.effective_chat.id  # type: ignore[union-attr]
    client = _get_client(context)

    logger.info(f"Chat message: {text[:80]!r}")

    # Read receipt — show "typing..." immediately
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Thinking placeholder
    thinking_msg = await update.message.reply_text(_THINKING_PLACEHOLDER)

    # Keep the typing indicator alive while waiting for the LLM
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, chat_id, stop_typing))

    try:
        response = await client.chat(text)
        logger.info(f"Response received ({len(response)} chars)")
        await _send_response(thinking_msg, chat_id, context.bot, response, _max_response_chars(context))
    except JarvisBusyError as exc:
        logger.warning(f"Jarvis busy: {exc}")
        await thinking_msg.edit_text(f"Jarvis is busy talking to {exc.current_client}. Try again shortly.")
    except JarvisTimeoutError:
        logger.error("Jarvis chat timed out")
        await thinking_msg.edit_text("Jarvis timed out. Try again.")
    except JarvisServerError as exc:
        logger.error(f"Jarvis server error: {exc}")
        await thinking_msg.edit_text("Something went wrong. Check logs.")
    except BadRequest as exc:
        logger.error(f"Telegram API error: {exc}")
        await context.bot.send_message(chat_id=chat_id, text="Failed to send response (Telegram error).")
    except Exception as exc:
        logger.exception(f"Unexpected error in chat handler: {exc}")
        try:
            await thinking_msg.edit_text("Something went wrong. Check logs.")
        except BadRequest:
            pass
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Command handlers — deterministic, bypass the LLM
# ---------------------------------------------------------------------------

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — welcome message on first interaction."""
    if not _is_authorized(update, context):
        return
    if update.message is None:
        return

    logger.info(f"/start from user {update.effective_user.id}")  # type: ignore[union-attr]
    await update.message.reply_text("Jarvis is ready. Send any message to chat, or /help for commands.")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — show Jarvis server state."""
    if not _is_authorized(update, context):
        return
    if update.message is None:
        return

    logger.info("/status command")
    client = _get_client(context)
    try:
        data = await client.status()
        lines = [
            f"Ready: {data.get('ready', '?')}",
            f"Model: {data.get('model', '?')}",
            f"Session tokens: {data.get('session_tokens', '?')}",
            f"Heartbeat: {data.get('heartbeat_enabled', '?')}",
            f"Busy: {data.get('busy', '?')}",
        ]
        if data.get("current_client"):
            lines.append(f"Current client: {data['current_client']}")
        await update.message.reply_text("\n".join(lines))
    except Exception as exc:
        logger.exception(f"/status failed: {exc}")
        await update.message.reply_text("Could not reach Jarvis server.")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — list available commands."""
    if not _is_authorized(update, context):
        return
    if update.message is None:
        return

    logger.info("/help command")
    text = (
        "Commands:\n"
        "/start   \u2014 welcome message\n"
        "/status  \u2014 Jarvis server status\n"
        "/help    \u2014 this message\n"
        "\n"
        "Anything else is sent to Jarvis as a chat message."
    )
    await update.message.reply_text(text)
