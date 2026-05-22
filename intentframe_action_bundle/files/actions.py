"""Files bundle action ids."""

from __future__ import annotations

from action_registry.types import ActionType

WRITE_FILE_ACTIONS = frozenset({
    ActionType.WRITE_FILE.value,
    ActionType.WRITE_HOST_FILE.value,
})
