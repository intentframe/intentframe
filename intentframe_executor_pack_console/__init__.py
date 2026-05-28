"""Neutral console executor pack for non-GUI user interaction."""

from __future__ import annotations

from intentframe_executor_pack_console.adapters import register_all_adapters

__all__ = ["register_all", "register_all_adapters"]


def register_all() -> None:
    """Register all console pack implementations."""
    register_all_adapters()
