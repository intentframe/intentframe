"""Snapshot/restore helpers for the process-wide bundle registry in tests.

Integration tests that call ``shutdown_bundles()`` or ``runtime.aclose()``
mutate registry singletons (notably ``EmailActionBundle``). Use
:func:`isolated_bundle_registry` to restore registry tables and replace the
email bundle with a fresh instance after each test.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import intentframe_bundle_sdk.loader as loader
import intentframe_bundle_sdk.registry as registry


@dataclass(frozen=True)
class _RegistrySnapshot:
    action_by_id: dict[str, Any]
    action_instances: list[Any]
    domain_by_id: dict[str, Any]
    action_to_domains: dict[str, tuple[str, ...]]
    routed_domain_ids: frozenset[str]
    loaded_packages: frozenset[str] | None


def capture_registry_snapshot() -> _RegistrySnapshot:
    return _RegistrySnapshot(
        action_by_id=registry._ACTION_BY_ID.copy(),
        action_instances=list(registry._ACTION_INSTANCES),
        domain_by_id=registry._DOMAIN_BY_ID.copy(),
        action_to_domains=dict(registry._ACTION_TO_DOMAINS),
        routed_domain_ids=registry._ROUTED_DOMAIN_IDS,
        loaded_packages=loader._LOADED_PACKAGES,
    )


def restore_registry_snapshot(snap: _RegistrySnapshot) -> None:
    registry._ACTION_BY_ID.clear()
    registry._ACTION_BY_ID.update(snap.action_by_id)
    registry._ACTION_INSTANCES.clear()
    registry._ACTION_INSTANCES.extend(snap.action_instances)
    registry._DOMAIN_BY_ID.clear()
    registry._DOMAIN_BY_ID.update(snap.domain_by_id)
    registry._ACTION_TO_DOMAINS.clear()
    registry._ACTION_TO_DOMAINS.update(snap.action_to_domains)
    registry._ROUTED_DOMAIN_IDS = snap.routed_domain_ids
    loader._LOADED_PACKAGES = snap.loaded_packages


def refresh_email_bundle_in_registry() -> None:
    """Replace the shared email registry singleton with a fresh instance."""
    from intentframe_native_kit.intentframe_native_bundles.actions.email.bundle import EmailActionBundle

    fresh = EmailActionBundle()
    registry._ACTION_INSTANCES[:] = [
        bundle for bundle in registry._ACTION_INSTANCES if bundle.bundle_id != "email"
    ]
    registry._ACTION_INSTANCES.append(fresh)
    for action_id in fresh.action_ids:
        registry._ACTION_BY_ID[action_id] = fresh


@contextmanager
def isolated_bundle_registry() -> Iterator[None]:
    snap = capture_registry_snapshot()
    try:
        yield
    finally:
        restore_registry_snapshot(snap)
        refresh_email_bundle_in_registry()
