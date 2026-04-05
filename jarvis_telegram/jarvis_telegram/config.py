"""Telegram bot configuration.

Uses pydantic-settings so env vars (JARVIS_TELEGRAM_*) are the primary
config source.  No YAML layer — the bot is lightweight and env-only.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_TELEGRAM_",
        env_ignore_empty=True,
    )

    bot_token: str
    allowed_user_id: int
    jarvis_socket_path: str = "/tmp/jarvis.sock"
    max_response_chars: int = 16_384


def load_config() -> TelegramConfig:
    return TelegramConfig()
