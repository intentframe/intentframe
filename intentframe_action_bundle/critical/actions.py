"""Critical action ids — aggregated for AE / Guardian prompt routing."""

from __future__ import annotations

from action_registry.types import ActionType

# Actions with no family-specific bundle gate but always on critical AI lane.
CRITICAL_ONLY_ACTIONS: frozenset[str] = frozenset({
    ActionType.PAY_INVOICE.value,
    ActionType.DELETE_FILE.value,
    ActionType.DELETE_EVENT.value,
    ActionType.DELETE_REMINDER.value,
    ActionType.DELETE_CONTACT.value,
    ActionType.DELETE_NOTE.value,
    ActionType.DELETE_EMAIL.value,
    ActionType.SEND_EMAIL.value,
    ActionType.HTTP_POST.value,
})
