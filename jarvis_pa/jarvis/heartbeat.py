"""Periodic proactive check runner.

Reads HEARTBEAT.md for instructions, evaluates them via LLM on a
configurable interval, deduplicates alerts (using diskcache with 24h TTL
so dedup survives restarts), and delivers macOS notifications via
desktop-notifier when something needs user attention.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

from diskcache import Cache
from loguru import logger

if TYPE_CHECKING:
    from jarvis.agent import JarvisAgent

from jarvis.config import JarvisConfig

HEARTBEAT_OK = "HEARTBEAT_OK"

# 24-hour dedup window (seconds)
_DEDUP_TTL = 86_400


class HeartbeatRunner:
    """Async background task that runs periodic proactive checks."""

    def __init__(self, agent: JarvisAgent, config: JarvisConfig) -> None:
        self.agent = agent
        self.config = config
        self._task: asyncio.Task[None] | None = None
        self._event_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._notifier: Any | None = None
        # diskcache persists dedup hashes across restarts (24h TTL each).
        cache_dir = str(config.workspace_dir / "cache" / "heartbeat")
        self._dedup_cache: Cache = Cache(cache_dir)

    def set_event_callback(self, callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Register a callback invoked on every heartbeat alert (e.g. EventBus.publish)."""
        self._event_callback = callback

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Launch the heartbeat background loop."""
        if not self.config.heartbeat_enabled:
            logger.debug("Heartbeat disabled in config")
            return
        self._task = asyncio.create_task(self._run_loop(), name="heartbeat")
        logger.info("Heartbeat started")

    async def stop(self) -> None:
        """Cancel the heartbeat background loop and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.debug("Heartbeat stopped")

    # -- loop ----------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Sleep → check active hours → run once → repeat."""
        interval = self.config.heartbeat_interval_minutes * 60
        while True:
            try:
                await asyncio.sleep(interval)
                if self._within_active_hours():
                    await self._run_once()
                else:
                    logger.debug("Heartbeat: outside active hours, skipping")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Heartbeat loop error: {exc}")
                # Don't crash — sleep and retry.
                await asyncio.sleep(60)

    async def _run_once(self) -> None:
        """Read HEARTBEAT.md, evaluate via LLM, notify if needed."""
        logger.debug("Heartbeat: running check")

        try:
            heartbeat_md = await self.agent.memory.read_file("HEARTBEAT.md")
            if not heartbeat_md.strip():
                logger.debug("Heartbeat: HEARTBEAT.md is empty, skipping")
                return

            prompt = (
                f"These are your proactive check instructions:\n\n"
                f"{heartbeat_md}\n\n"
                f"Evaluate each check now. If everything looks fine, respond with exactly: "
                f"{HEARTBEAT_OK}\n"
                f"Otherwise, summarise what needs attention in {self.config.heartbeat_ack_max_chars} chars or fewer."
            )
            response = await self.agent.run_single(prompt)
            response = response.strip()

            if HEARTBEAT_OK in response:
                logger.debug("Heartbeat: all clear")
                return

            # Check dedup before alerting.
            if self._is_duplicate(response):
                logger.debug(f"Heartbeat: duplicate alert suppressed: {response[:40]!r}")
                return

            logger.info(f"Heartbeat alert: {response[:60]!r}")
            await self._send_notification(response)
            self._record_sent(response)

        except Exception as exc:
            logger.error(f"Heartbeat _run_once error: {exc}")

    # -- helpers -------------------------------------------------------------

    def _within_active_hours(self) -> bool:
        """Return True if current time is inside the configured active window."""
        now = datetime.now().time()
        try:
            start_h, start_m = map(int, self.config.heartbeat_active_hours_start.split(":"))
            end_h, end_m = map(int, self.config.heartbeat_active_hours_end.split(":"))
            start = time(start_h, start_m)
            end = time(end_h, end_m)
        except (ValueError, AttributeError):
            return True  # Malformed config → don't block

        if start <= end:
            return start <= now <= end
        # Overnight window (e.g. 22:00 – 06:00)
        return now >= start or now <= end

    def _is_duplicate(self, alert_text: str) -> bool:
        """Return True if this alert was already sent in the last 24h."""
        key = self._alert_key(alert_text)
        return key in self._dedup_cache

    def _record_sent(self, alert_text: str) -> None:
        """Store the alert hash in diskcache with a 24h TTL."""
        key = self._alert_key(alert_text)
        self._dedup_cache.set(key, True, expire=_DEDUP_TTL)

    @staticmethod
    def _alert_key(text: str) -> str:
        """Short stable hash of the alert text."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def _send_notification(self, message: str) -> None:
        """Send a macOS notification via desktop-notifier, fall back to actor."""
        # Truncate to configured max chars.
        body = message[:self.config.heartbeat_ack_max_chars]

        # Push to the event bus (API server clients) if wired.
        if self._event_callback is not None:
            try:
                await self._event_callback({"type": "heartbeat_alert", "message": body})
            except Exception as exc:
                logger.debug(f"Event callback failed: {exc}")

        try:
            if self._notifier is None:
                from desktop_notifier import DesktopNotifier
                self._notifier = DesktopNotifier(app_name="Jarvis")
            await self._notifier.send(title="Jarvis", message=body)
            logger.debug("Heartbeat notification sent via desktop-notifier")
            return
        except Exception as exc:
            logger.debug(f"desktop-notifier unavailable ({exc}), falling back to actor")

        # Fallback: route through IntentFrame pipeline.
        try:
            await self.agent.actor.submit({
                "action": "SHOW_NOTIFICATION",
                "title": "Jarvis",
                "body": body,
                "reason": "Proactive heartbeat alert",
            })
        except Exception as exc:
            logger.warning(f"Heartbeat notification fallback also failed: {exc}")
