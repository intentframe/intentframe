"""Shared test helper for loading first-party bundles into the SDK registry."""

from __future__ import annotations

from intentframe_components.guardian.deterministic import DeterministicGuardian
from intentframe_bundle_sdk.loader import ensure_loaded

DEFAULT_TEST_PACKAGES = ["intentframe_native_kit.intentframe_native_bundles"]


def ensure_test_bundles_loaded() -> None:
    """Register native bundles once per process via the SDK loader."""
    ensure_loaded(DEFAULT_TEST_PACKAGES)


def make_deterministic_guardian(*, verbose: bool = False) -> DeterministicGuardian:
    """Build a deterministic guardian with the explicit test bundle set."""
    return DeterministicGuardian(packages=DEFAULT_TEST_PACKAGES, verbose=verbose)
