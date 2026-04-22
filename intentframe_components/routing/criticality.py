"""
Action-level criticality classification for AE / Guardian prompt routing.

``CRITICAL_ACTIONS`` is the set of action types that are **always**
critical — every invocation of one of these actions rides the critical
AE / Guardian prompt lane regardless of content.  It is the coarse
action-level gate; the finer content-aware gates live elsewhere.

Rationale — always-critical categories:

- Arbitrary-code execution (RUN_COMMAND)
- Financial impact (PAY_INVOICE)
- Irreversible data loss (DELETE_FILE, DELETE_HOST_FILE, DELETE_EVENT,
  DELETE_REMINDER, DELETE_CONTACT, DELETE_NOTE, DELETE_EMAIL)
- External communication / social-engineering vectors (SEND_EMAIL)
- External network / exfiltration vectors (HTTP_POST)

WRITE_FILE and WRITE_HOST_FILE are intentionally **not** in this set —
they share a dedicated AE lane (``critical_write_file``).  Every write
(virtual or host) rides that lane unconditionally; ``FileIntel`` is
handed to the AE as context inside the payload but does not affect
prompt-id selection.
Content-aware WRITE_FILE sub-lanes (e.g. a future
``critical_write_file_code`` for positively-classified code payloads)
are deferred — when added they will be full-body forks of the existing
``critical_write_file`` body, not additive overlays.  The
destination-sensitive side is handled earlier, deterministically, by
:class:`DeterministicGuardian` which BLOCKs writes that land on
sensitive system locations (see
``intentframe_components.heuristics.file_payload.is_sensitive_write_path``).

The Guardian side routes purely on this action-level set today; that
is a deliberate choice, not an oversight — content-aware Guardian
lanes can be added later without revisiting this file.

The set is a ``frozenset[str]`` of action-value strings (not enum
members) so callers can look it up without importing :class:`ActionType`
into every hot path.
"""

from __future__ import annotations

from action_registry.types import ActionType


CRITICAL_ACTIONS: frozenset[str] = frozenset({
    ActionType.RUN_COMMAND.value,
    ActionType.PAY_INVOICE.value,
    ActionType.DELETE_FILE.value,
    ActionType.DELETE_HOST_FILE.value,
    ActionType.DELETE_EVENT.value,
    ActionType.DELETE_REMINDER.value,
    ActionType.DELETE_CONTACT.value,
    ActionType.DELETE_NOTE.value,
    ActionType.DELETE_EMAIL.value,
    ActionType.SEND_EMAIL.value,
    ActionType.HTTP_POST.value,
})


def is_critical(action_value: str) -> bool:
    """Return True if ``action_value`` belongs to the critical set.

    Accepts the action's string value (``intent.action.value``) so
    callers don't have to import the enum.  Unknown / unregistered
    actions return False — criticality is opt-in, not opt-out.
    """
    return action_value in CRITICAL_ACTIONS
