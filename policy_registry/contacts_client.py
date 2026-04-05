"""
Client for resolving contact-based recipient sources via the platform server.

The Policy Registry calls this at serve time to resolve RecipientSource /
ContactSource rules into flat email/contact lists. Results are cached
with a short TTL to avoid hammering the Contacts.framework on every request.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET = Path.home() / ".intentframe" / "run" / "platform.sock"
_TIMEOUT = 10.0
_CACHE_TTL = 60.0


def _socket_path() -> str:
    return os.environ.get("PLATFORM_SOCKET", str(_DEFAULT_SOCKET))


class PlatformContactsClient:
    """Resolves contact sources by querying the native platform server."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[str]]] = {}

    def _cache_key(self, source: str, filter_val: str) -> str:
        return f"{source}:{filter_val}"

    def _get_cached(self, key: str) -> list[str] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > _CACHE_TTL:
            del self._cache[key]
            return None
        return data

    def _set_cached(self, key: str, data: list[str]) -> None:
        self._cache[key] = (time.monotonic(), data)

    def invalidate(self) -> None:
        """Clear all cached contact data."""
        self._cache.clear()

    async def fetch_all_emails(self) -> list[str]:
        """Fetch all contact email addresses from the platform."""
        cache_key = self._cache_key("contacts_all", "")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            transport = httpx.AsyncHTTPTransport(uds=_socket_path())
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://platform-server",
                timeout=_TIMEOUT,
            ) as client:
                resp = await client.post(
                    "/execute",
                    json={
                        "adapter": "contacts",
                        "action": "FETCH_ALL_CONTACT_EMAILS",
                        "params": {},
                    },
                )
                resp.raise_for_status()
                body = resp.json()

            if body.get("success") is True:
                emails = body.get("data", {}).get("emails", [])
                self._set_cached(cache_key, emails)
                logger.debug("Resolved %d contact emails (all)", len(emails))
                return emails

            logger.warning("Platform returned non-success for contact emails: %s", body)
            return []
        except httpx.ConnectError:
            logger.warning("Platform server unreachable — cannot resolve contact emails")
            return []
        except Exception:
            logger.exception("Failed to resolve contact emails")
            return []

    async def fetch_group_emails(self, group: str) -> list[str]:
        """Fetch email addresses from a specific contact group."""
        cache_key = self._cache_key("contacts_group", group)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            transport = httpx.AsyncHTTPTransport(uds=_socket_path())
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://platform-server",
                timeout=_TIMEOUT,
            ) as client:
                resp = await client.post(
                    "/execute",
                    json={
                        "adapter": "contacts",
                        "action": "FETCH_GROUP_CONTACT_EMAILS",
                        "params": {"group": group},
                    },
                )
                resp.raise_for_status()
                body = resp.json()

            if body.get("success") is True:
                emails = body.get("data", {}).get("emails", [])
                self._set_cached(cache_key, emails)
                logger.debug("Resolved %d contact emails (group: %s)", len(emails), group)
                return emails

            logger.warning("Platform returned non-success for group contacts: %s", body)
            return []
        except httpx.ConnectError:
            logger.warning("Platform server unreachable — cannot resolve group contacts")
            return []
        except Exception:
            logger.exception("Failed to resolve group contacts")
            return []

    async def resolve_sources(
        self,
        sources: list,
    ) -> list[str]:
        """Resolve a list of RecipientSource or ContactSource into email/contact strings."""
        resolved: list[str] = []
        for src in sources:
            if not src.enabled:
                continue
            if src.source == "contacts_all":
                resolved.extend(await self.fetch_all_emails())
            elif src.source == "contacts_group":
                resolved.extend(await self.fetch_group_emails(src.filter))
            else:
                logger.warning("Unknown source type: %s", src.source)
        return resolved
