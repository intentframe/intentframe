"""
Criticality classification for AE / Guardian prompt routing.

``CRITICAL_ACTIONS`` is the deterministic set of :class:`ActionType`
values that, when they reach the AI path (i.e. after
:class:`DeterministicGuardian` returned UNDECIDED), should be evaluated
under a **critical** prompt rather than the standard prompt.

Rationale (see ``TODO/AE_Guardian_specialisation_routes.md``):

- Arbitrary-code execution (RUN_COMMAND)
- Financial impact (PAY_INVOICE)
- Irreversible data loss (DELETE_FILE, DELETE_EVENT, DELETE_REMINDER,
  DELETE_CONTACT, DELETE_NOTE, DELETE_EMAIL)
- External communication / social-engineering vectors (SEND_EMAIL)
- External network / exfiltration vectors (HTTP_POST)

WRITE_FILE is intentionally **not** in this set.  It is routed based on
``command_intel`` content in a later bundle (jarvis write-file policy)
— see ``TODO/jarvis-write-file-policy-and-python-env.md``.

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
