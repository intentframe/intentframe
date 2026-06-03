"""Domain routing manifest — maps domain_id to action ids (not owned by DomainBundle)."""

from __future__ import annotations

from intentframe_native_kit.action_registry.types import ActionType, DomainType

DOMAIN_ROUTES: dict[str, frozenset[str]] = {
    DomainType.FINANCE.value: frozenset({ActionType.PAY_INVOICE.value}),
    DomainType.DELETION.value: frozenset({
        ActionType.DELETE_FILE.value,
        ActionType.DELETE_HOST_FILE.value,
        # Path-oriented ``DeletionIntentData`` only — record deletes need a
        # generalized schema before routing (DELETE_EVENT, DELETE_REMINDER, …).
        # ActionType.DELETE_EVENT.value,
        # ActionType.DELETE_REMINDER.value,
        # ActionType.DELETE_CONTACT.value,
        # ActionType.DELETE_NOTE.value,
    }),
}
