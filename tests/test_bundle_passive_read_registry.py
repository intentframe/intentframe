"""Registry invariants for action bundle registration."""

from __future__ import annotations

import pytest

from intentframe_action_bundle import ensure_bundles_registered
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.registry import (
    all_passive_read_action_ids,
    register_action_bundle,
)


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_bundles_registered()


def test_passive_read_action_ids_are_subset_of_action_ids() -> None:
    from intentframe_bundle_sdk.registry import all_action_bundles

    for bundle in all_action_bundles():
        assert bundle.passive_read_action_ids.issubset(bundle.action_ids), (
            f"{bundle.bundle_id!r} passive_read_action_ids not subset of action_ids"
        )


def test_all_passive_read_action_ids_non_empty_after_register() -> None:
    ids = all_passive_read_action_ids()
    assert "READ_FILE" in ids
    assert "RUN_COMMAND" not in ids


def test_register_rejects_passive_read_outside_action_ids() -> None:
    class BadBundle(ActionBundle):
        bundle_id = "bad"
        action_ids = frozenset({"A"})
        passive_read_action_ids = frozenset({"B"})

    with pytest.raises(ValueError, match="passive_read_action_ids"):
        register_action_bundle(BadBundle())
