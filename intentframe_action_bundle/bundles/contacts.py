"""Contacts action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle

_CONTACT_READ_ACTIONS = frozenset({
    ActionType.SEARCH_CONTACTS.value,
    ActionType.GET_CONTACT.value,
})

_CONTACT_WRITE_ACTIONS = frozenset({
    ActionType.ADD_CONTACT.value,
    ActionType.UPDATE_CONTACT.value,
    ActionType.DELETE_CONTACT.value,
})


class ContactsActionBundle(ActionBundle):
    bundle_id = "contacts"
    action_ids = _CONTACT_READ_ACTIONS | _CONTACT_WRITE_ACTIONS
    passive_read_action_ids = _CONTACT_READ_ACTIONS
