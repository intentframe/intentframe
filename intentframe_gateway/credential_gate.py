"""Credential gate — checks mandatory/optional credentials at startup.

The gate queries the credential vault to determine:
1. Whether mandatory credentials (OpenAI API key) exist
2. Which optional services (EDI, Telegram) can start
3. The **secret** runtime env dict to inject into child processes

This module handles **secrets only** (API keys, tokens, passwords).
Non-sensitive configuration (user_id, Telegram allowed_user_id, etc.) is
managed by ``config_loader.py`` via ``~/.intentframe/gateway.yaml``.

At startup, the gateway merges both layers::

    config_env   = config_loader.build_config_env()   # non-sensitive YAML
    runtime_env  = gate.build_runtime_env()            # vault secrets
    combined_env = {**config_env, **runtime_env}       # secrets win on collision

``build_runtime_env()`` returns one flat dict of every ``runtime_env`` credential
(keyed by each record's ``env_name``).

Credential metadata may include ``allowed_consumers``, but this module does not
filter on it; all runtime env vars are included for every recipient process.

The vault must already be healthy before calling any gate method.
"""

from __future__ import annotations

import logging
from pathlib import Path

from intentframe_credentials.client import VaultClient

logger = logging.getLogger(__name__)

_EMAIL_CONFIG_YAML = Path("~/.intentframe/email/config.yaml").expanduser()


class CredentialGate:
    """Pre-flight credential checks for the gateway startup sequence."""

    def __init__(self, vault: VaultClient) -> None:
        self._vault = vault

    async def check_mandatory(self) -> bool:
        """Return True if all mandatory credentials exist in the vault."""
        has_key = await self._vault.has("openai", "api_key")
        if not has_key:
            logger.warning("Mandatory credential missing: openai/api_key")
        return has_key

    async def check_optional(self) -> dict[str, bool]:
        """Check which optional services have their credentials configured."""
        return {
            "edi": await self._has_email_accounts(),
            "telegram": await self._vault.has("telegram", "bot_token"),
        }

    async def build_runtime_env(self) -> dict[str, str]:
        """Fetch every ``runtime_env`` credential into one {env_name: value} dict.

        No per-consumer filtering: the same mapping is merged into each child
        the gateway starts (supervisor + Jarvis + Telegram, etc.). See gateway
        README, section "Runtime env injection (one dict, every child)".

        Calls ``GET /v1/runtime-env`` for metadata, then fetches each
        value individually.  The resulting dict is passed to child
        process environments by the process manager and supervisor.
        """
        records = await self._vault.list_runtime_env()
        env: dict[str, str] = {}
        for rec in records:
            env_name = rec.get("env_name")
            if not env_name:
                continue
            value = await self._vault.get(rec["namespace"], rec["key"])
            if value:
                env[env_name] = value
        logger.info("Built runtime env with %d variable(s)", len(env))
        return env

    async def _has_email_accounts(self) -> bool:
        """Check if EDI email accounts are configured (config.yaml exists and non-empty)."""
        if not _EMAIL_CONFIG_YAML.exists():
            return False
        try:
            import yaml
            raw = yaml.safe_load(_EMAIL_CONFIG_YAML.read_text(encoding="utf-8"))
            accounts = raw.get("accounts", []) if raw else []
            if not accounts:
                return False
            for account in accounts:
                email = account.get("email", "")
                if email and await self._vault.has(f"email.{email}", "password"):
                    return True
            return False
        except Exception:
            logger.debug("Could not read EDI email config", exc_info=True)
            return False
