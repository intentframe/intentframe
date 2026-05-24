"""Clipboard action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle


class ClipboardActionBundle(ActionBundle):
    bundle_id = "clipboard"
    action_ids = frozenset({
        ActionType.GET_CLIPBOARD.value,
        ActionType.SET_CLIPBOARD.value,
    })
    passive_read_action_ids = frozenset({ActionType.GET_CLIPBOARD.value})
