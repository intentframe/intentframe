"""First-party action bundles — lazy public exports only.

Plugin package layout: one folder per action family under
``intentframe_action_bundle/``; bundle classes in ``bundles/`` (fold into
``<family>/bundle.py`` in PR A). Shared code stays in the owning family —
``files/`` owns file-write tooling; ``host_files/`` imports it. Other
families keep their logic local. See ``files/__init__.py`` and
``intentframe_bundle_sdk.action`` for the full convention.
"""

from __future__ import annotations

__all__ = [
    "passive_read_action_ids",
]


def passive_read_action_ids() -> frozenset[str]:
    """Registered passive-read action ids (SDK-owned fast path)."""
    from intentframe_action_bundle.bundles.register import ensure_bundles_registered
    from intentframe_bundle_sdk.registry import all_passive_read_action_ids

    ensure_bundles_registered()
    return all_passive_read_action_ids()
