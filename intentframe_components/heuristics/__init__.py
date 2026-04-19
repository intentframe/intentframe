"""
Shared, engine-neutral classification heuristics.

These predicates answer *domain* questions about an intent — "is this
destination a sensitive system location?" — without taking a stance
on what the consumer does with the answer.

They live here (not inside ``guardian/deterministic``) so that any
future callers (prompt strategy, policy registry, audit tooling) can
consume the same vocabulary without routing through DG.

Caller today:
  - ``intentframe_components.guardian.deterministic.DeterministicGuardian`` —
    uses ``is_sensitive_write_path`` as a *BLOCK* rule on WRITE_FILE
    (virtual-path peer of the VFS floor at
    ``resource_registry.floor.DENY_WRITE_PREFIXES``).  DG does not
    consult any payload-content heuristics — content-based ALLOW
    fast-paths are unsound under an adversarial agent, so DG never
    shortcuts a mutating write based on payload shape.

``DefaultPromptStrategy`` used to route WRITE_FILE onto payload-aware
lanes via helpers in this package; that branch has been removed.
WRITE_FILE now rides a single flat lane (``critical_write_file``)
and ``FileIntel`` is forwarded to the AE as payload context only.
"""

from intentframe_components.heuristics.file_payload import (
    SENSITIVE_WRITE_PATH_FRAGMENTS,
    is_sensitive_write_path,
)

__all__ = [
    "SENSITIVE_WRITE_PATH_FRAGMENTS",
    "is_sensitive_write_path",
]
