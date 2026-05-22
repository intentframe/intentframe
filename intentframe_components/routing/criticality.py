"""
Action-level criticality classification for AE / Guardian prompt routing.

``CRITICAL_ACTIONS`` is aggregated in ``intentframe_action_bundle.taxonomy``.
"""

from __future__ import annotations

from intentframe_action_bundle.taxonomy import CRITICAL_ACTIONS, is_critical

__all__ = ["CRITICAL_ACTIONS", "is_critical"]
