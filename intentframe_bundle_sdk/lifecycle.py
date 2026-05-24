"""Bundle startup and shutdown orchestration."""

from __future__ import annotations

import asyncio
import logging

from intentframe_bundle_sdk.registry import all_action_bundles, all_domain_bundles

logger = logging.getLogger(__name__)

DEFAULT_CLOSE_TIMEOUT_S = 5.0


async def startup_bundles() -> None:
    """Run optional startup hooks on every registered bundle."""
    for bundle in (*all_action_bundles(), *all_domain_bundles()):
        await bundle.startup()


async def shutdown_bundles(*, timeout_s: float = DEFAULT_CLOSE_TIMEOUT_S) -> None:
    """Release bundle-owned resources. Failures are aggregated, not swallowed."""
    errors: list[BaseException] = []
    bundles = list(all_domain_bundles()) + list(all_action_bundles())
    for bundle in reversed(bundles):
        try:
            await asyncio.wait_for(bundle.aclose(), timeout=timeout_s)
        except BaseException as exc:
            logger.exception("bundle aclose failed: %s", bundle.bundle_id)
            errors.append(exc)
    if errors:
        raise BaseExceptionGroup("bundle shutdown failures", errors)
