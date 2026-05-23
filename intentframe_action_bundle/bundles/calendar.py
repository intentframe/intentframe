"""Calendar action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle

_CALENDAR_READ_ACTIONS = frozenset({
    ActionType.LIST_CALENDARS.value,
    ActionType.LIST_EVENTS.value,
    ActionType.SEARCH_EVENTS.value,
})

_CALENDAR_WRITE_ACTIONS = frozenset({
    ActionType.CREATE_EVENT.value,
    ActionType.UPDATE_EVENT.value,
    ActionType.DELETE_EVENT.value,
})


class CalendarActionBundle(ActionBundle):
    bundle_id = "calendar"
    action_ids = _CALENDAR_READ_ACTIONS | _CALENDAR_WRITE_ACTIONS
    passive_read_action_ids = _CALENDAR_READ_ACTIONS
