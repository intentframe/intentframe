"""Shared test helper for loading first-party bundles into the SDK registry."""

from __future__ import annotations

from intentframe_native_bundles import _ensure_first_party_bundles_loaded


def ensure_test_bundles_loaded() -> None:
    """Register native bundles once per process (shim until Wave D loader)."""
    _ensure_first_party_bundles_loaded()
