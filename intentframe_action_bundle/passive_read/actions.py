"""Passive-read action ids — canonical source for DG and AE fast paths."""

from __future__ import annotations

from action_registry.types import ActionType

PASSIVE_READ_ACTIONS: frozenset[str] = frozenset({
    ActionType.READ_FILE.value,
    ActionType.LIST_DIRECTORY.value,
    ActionType.READ_HOST_FILE.value,
    ActionType.LIST_HOST_DIRECTORY.value,
    ActionType.LIST_CALENDARS.value,
    ActionType.LIST_EVENTS.value,
    ActionType.SEARCH_EVENTS.value,
    ActionType.LIST_REMINDERS.value,
    ActionType.LIST_REMINDER_LISTS.value,
    ActionType.SEARCH_CONTACTS.value,
    ActionType.GET_CONTACT.value,
    ActionType.LIST_NOTES.value,
    ActionType.READ_NOTE.value,
    ActionType.READ_MESSAGES.value,
    ActionType.READ_EMAIL.value,
    ActionType.SEARCH_EMAIL.value,
    ActionType.GET_EMAIL.value,
    ActionType.DOWNLOAD_ATTACHMENT.value,
    ActionType.GET_CLIPBOARD.value,
    ActionType.SEARCH_SPOTLIGHT.value,
    ActionType.GET_SYSTEM_INFO.value,
    ActionType.GET_BRIGHTNESS.value,
    ActionType.GET_VOLUME.value,
    ActionType.GET_MUTE.value,
    ActionType.GET_DARK_MODE.value,
})
