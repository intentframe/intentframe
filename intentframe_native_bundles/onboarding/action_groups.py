"""Action-id groupings for onboarding guardrail generation (bundle-owned vocabulary)."""

from __future__ import annotations

from action_registry.types import ActionType

VFS_FILE_ACTIONS: frozenset[str] = frozenset({
    ActionType.READ_FILE.value,
    ActionType.LIST_DIRECTORY.value,
    ActionType.WRITE_FILE.value,
    ActionType.DELETE_FILE.value,
})

HOST_FILE_ACTIONS: frozenset[str] = frozenset({
    ActionType.READ_HOST_FILE.value,
    ActionType.LIST_HOST_DIRECTORY.value,
    ActionType.WRITE_HOST_FILE.value,
    ActionType.DELETE_HOST_FILE.value,
})

MUTATING_FILE_ACTIONS: frozenset[str] = frozenset({
    ActionType.WRITE_FILE.value,
    ActionType.DELETE_FILE.value,
    ActionType.WRITE_HOST_FILE.value,
    ActionType.DELETE_HOST_FILE.value,
})

OUTBOUND_EMAIL_ACTIONS: frozenset[str] = frozenset({
    ActionType.SEND_EMAIL.value,
    ActionType.REPLY_EMAIL.value,
    ActionType.FORWARD_EMAIL.value,
})

FINANCIAL_ACTIONS: frozenset[str] = frozenset({
    ActionType.PAY_INVOICE.value,
    ActionType.HTTP_POST.value,
})

TERMINAL_ACTIONS: frozenset[str] = frozenset({
    ActionType.RUN_COMMAND.value,
})

USER_IO_ACTIONS: frozenset[str] = frozenset({
    ActionType.ASK_USER.value,
})
