"""Spotlight action bundle."""

from __future__ import annotations

from intentframe_native_kit.action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle


class SpotlightActionBundle(ActionBundle):
    bundle_id = "spotlight"
    action_ids = frozenset({ActionType.SEARCH_SPOTLIGHT.value})
    passive_read_action_ids = frozenset({ActionType.SEARCH_SPOTLIGHT.value})
