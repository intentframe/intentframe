"""
macOS TCC permission checker for the executor.

Queries the native platform server (macos-appkit-server) for current
TCC permission status. The platform server owns the actual TCC grants
and reports their state via GET /permissions.

No pyobjc dependency — all TCC interaction is handled by the Swift server.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger("executor.permissions")

# Adapters whose capabilities are gated by a macOS TCC grant. Only these need a
# permission check; everything else is always "granted".
TCC_ADAPTERS = frozenset({"calendar", "reminders", "contacts"})


async def _query_platform_server() -> dict | None:
    """Query the platform server's /permissions endpoint."""
    try:
        from .adapters._platform_client import platform_permissions
        return await platform_permissions()
    except Exception as exc:
        logger.warning(
            "Platform server not reachable: %s. "
            "TCC-gated features (calendar, reminders, contacts) will fail. "
            "Ensure macos-appkit-server is running.",
            exc,
        )
        return None


@lru_cache(maxsize=1)
def _platform_perms() -> dict:
    """Query the platform server once per process and cache the result.

    Returns the raw ``GET /permissions`` payload, or ``{}`` if the server is
    unreachable. Memoized so multiple adapters constructed at startup share a
    single round-trip rather than each issuing their own query.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            perms = pool.submit(
                lambda: asyncio.run(_query_platform_server())
            ).result(timeout=10)
    else:
        perms = asyncio.run(_query_platform_server())

    return perms or {}


def check_adapter_permission(adapter_id: str) -> bool:
    """Warn-only TCC permission check for a single adapter.

    Non-TCC adapters always pass. For TCC-gated adapters (calendar, reminders,
    contacts) this queries the cached platform-server state and logs a warning
    when the grant is missing or the server is unreachable. It never raises:
    callers (adapter ``__init__``) construct regardless — the action simply
    fails later if the grant is truly absent, preserving warn-only semantics.

    Args:
        adapter_id: The adapter being constructed.

    Returns:
        ``True`` if the grant is present (or the adapter is not TCC-gated),
        ``False`` if denied, unknown, or the check failed.
    """
    if adapter_id not in TCC_ADAPTERS:
        return True

    try:
        perms = _platform_perms()
    except Exception as exc:
        logger.warning("Platform server permission check failed for %s: %s", adapter_id, exc)
        return False

    if not perms:
        logger.warning("  %s: unknown (platform server unreachable)", adapter_id)
        return False

    detail = perms.get(adapter_id, {})
    granted = bool(detail.get("granted", False))
    if granted:
        logger.info("  %s: granted", adapter_id)
    else:
        hint = detail.get("hint", "Grant in System Settings > Privacy & Security")
        logger.warning("  %s: denied — %s — related features will fail.", adapter_id, hint)

    return granted


def check_permissions(enabled_adapters: list[str]) -> dict[str, bool]:
    """Check TCC permissions for a list of enabled adapters (warn-only).

    Thin wrapper over :func:`check_adapter_permission` retained for callers that
    want to check a batch up front. Per-adapter checks now run from each TCC
    adapter's ``__init__``; this helper shares the same memoized query.

    Args:
        enabled_adapters: List of adapter IDs from executor config.

    Returns:
        Dict mapping adapter-id to True/False for TCC-gated adapters.
    """
    needs_check = TCC_ADAPTERS & set(enabled_adapters)
    if not needs_check:
        return {}

    logger.info("Checking platform server permissions...")
    return {adapter: check_adapter_permission(adapter) for adapter in needs_check}
