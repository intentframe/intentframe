"""First-party action bundles — lazy public exports only."""

from __future__ import annotations

__all__ = [
    "CRITICAL_ACTIONS",
    "is_critical",
    "passive_read_action_ids",
]

from intentframe_action_bundle.taxonomy import CRITICAL_ACTIONS, is_critical


def passive_read_action_ids() -> frozenset[str]:
    """Registered passive-read action ids (SDK-owned fast path)."""
    from intentframe_action_bundle.bundles.register import ensure_bundles_registered
    from intentframe_bundle_sdk.registry import all_passive_read_action_ids

    ensure_bundles_registered()
    return all_passive_read_action_ids()
