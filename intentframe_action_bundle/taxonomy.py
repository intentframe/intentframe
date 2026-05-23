"""Aggregated action taxonomies — no imports from intentframe_components."""

from __future__ import annotations

from intentframe_action_bundle.critical.actions import CRITICAL_ONLY_ACTIONS
from intentframe_action_bundle.host_files.deterministic import CRITICAL_ACTIONS as HOST_CRITICAL
from intentframe_action_bundle.terminal import CRITICAL_ACTIONS as TERMINAL_CRITICAL

CRITICAL_ACTIONS: frozenset[str] = (
    CRITICAL_ONLY_ACTIONS | TERMINAL_CRITICAL | HOST_CRITICAL
)


def is_critical(action_value: str) -> bool:
    return action_value in CRITICAL_ACTIONS
