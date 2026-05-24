"""Notes action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle

_NOTES_READ_ACTIONS = frozenset({
    ActionType.LIST_NOTES.value,
    ActionType.READ_NOTE.value,
})

_NOTES_WRITE_ACTIONS = frozenset({
    ActionType.CREATE_NOTE.value,
    ActionType.DELETE_NOTE.value,
})


class NotesActionBundle(ActionBundle):
    bundle_id = "notes"
    action_ids = _NOTES_READ_ACTIONS | _NOTES_WRITE_ACTIONS
    passive_read_action_ids = _NOTES_READ_ACTIONS
