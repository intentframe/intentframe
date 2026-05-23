"""System read/write action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle

_SYSTEM_READ_ACTIONS = frozenset({
    ActionType.GET_SYSTEM_INFO.value,
    ActionType.GET_BRIGHTNESS.value,
    ActionType.GET_VOLUME.value,
    ActionType.GET_MUTE.value,
    ActionType.GET_DARK_MODE.value,
})

_SYSTEM_WRITE_ACTIONS = frozenset({
    ActionType.SET_VOLUME.value,
    ActionType.SET_BRIGHTNESS.value,
    ActionType.TOGGLE_MUTE.value,
    ActionType.TOGGLE_DARK_MODE.value,
})


class SystemActionBundle(ActionBundle):
    bundle_id = "system"
    action_ids = _SYSTEM_READ_ACTIONS | _SYSTEM_WRITE_ACTIONS
    passive_read_action_ids = _SYSTEM_READ_ACTIONS
