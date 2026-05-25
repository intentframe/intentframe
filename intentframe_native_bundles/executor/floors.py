"""Executor-time floor checks owned by action bundles."""

from __future__ import annotations

from action_registry.types import ActionType
from resource_registry.floor import match_deny_prefix

HOST_MUTATING_ACTIONS = frozenset({
    ActionType.WRITE_HOST_FILE.value,
    ActionType.DELETE_HOST_FILE.value,
})


def check_host_file_floor(canonical_path: str, action: str) -> str | None:
    """Return matched deny prefix if a host mutating action hits the floor."""
    if action not in HOST_MUTATING_ACTIONS:
        return None
    return match_deny_prefix(canonical_path)


def check_vfs_write_floor(canonical_path: str) -> str | None:
    """Return matched deny prefix if a VFS write/delete would hit the floor."""
    return match_deny_prefix(canonical_path)


def check_terminal_execute(command: str):
    """Run command_shield quick_check before terminal execute."""
    from command_shield import quick_check

    return quick_check(command)
