"""
macOS TCC permission checker for the executor.

Queries the native platform server (macos-appkit-server) for current
TCC permission status. The platform server owns the actual TCC grants
and reports their state via GET /permissions.

No pyobjc dependency — all TCC interaction is handled by the Swift server.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("executor.permissions")


async def _query_platform_server() -> dict | None:
    """Query the platform server's /permissions endpoint."""
    try:
        from executor.platforms.macos.adapters._platform_client import platform_permissions
        return await platform_permissions()
    except Exception as exc:
        logger.warning(
            "Platform server not reachable: %s. "
            "TCC-gated features (calendar, reminders, contacts) will fail. "
            "Ensure macos-appkit-server is running.",
            exc,
        )
        return None


def check_permissions(enabled_adapters: list[str]) -> dict[str, bool]:
    """Check TCC permissions for enabled adapters via the platform server.

    Queries the running macos-appkit-server for current permission state.
    If the server is unreachable, logs a warning and returns all-false.

    Args:
        enabled_adapters: List of adapter IDs from executor config.

    Returns:
        Dict mapping adapter-id to True/False for TCC-gated adapters.
    """
    import asyncio

    tcc_adapters = {"calendar", "reminders", "contacts"}
    needs_check = tcc_adapters & set(enabled_adapters)

    if not needs_check:
        return {}

    logger.info("Checking platform server permissions...")

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

    if perms is None:
        for adapter in needs_check:
            logger.warning("  %s: unknown (platform server unreachable)", adapter)
        return {a: False for a in needs_check}

    results: dict[str, bool] = {}
    for adapter in needs_check:
        detail = perms.get(adapter, {})
        granted = detail.get("granted", False)
        results[adapter] = granted
        if granted:
            logger.info("  %s: granted", adapter)
        else:
            hint = detail.get("hint", "Grant in System Settings > Privacy & Security")
            logger.warning("  %s: denied — %s", adapter, hint)

    granted_list = [k for k, v in results.items() if v]
    denied_list = [k for k, v in results.items() if not v]

    if granted_list:
        logger.info("Permissions granted: %s", ", ".join(granted_list))
    if denied_list:
        logger.warning(
            "Permissions denied: %s — related features will fail.",
            ", ".join(denied_list),
        )

    return results
