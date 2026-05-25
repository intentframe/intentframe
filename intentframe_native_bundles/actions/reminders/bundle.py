"""Reminders action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle

_REMINDER_READ_ACTIONS = frozenset({
    ActionType.LIST_REMINDER_LISTS.value,
    ActionType.LIST_REMINDERS.value,
})

_REMINDER_WRITE_ACTIONS = frozenset({
    ActionType.CREATE_REMINDER.value,
    ActionType.UPDATE_REMINDER.value,
    ActionType.COMPLETE_REMINDER.value,
    ActionType.DELETE_REMINDER.value,
})


class RemindersActionBundle(ActionBundle):
    bundle_id = "reminders"
    action_ids = _REMINDER_READ_ACTIONS | _REMINDER_WRITE_ACTIONS
    passive_read_action_ids = _REMINDER_READ_ACTIONS
