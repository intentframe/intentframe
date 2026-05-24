"""Domain constraints for the deletion domain."""

from __future__ import annotations

from typing import Literal, Optional

from action_registry.types import DomainType
from policy_registry.domains.base import DomainConstraints


class DeletionConstraints(DomainConstraints):
    """User-configured limits for the deletion domain.

    Enforced deterministically by the deletion Guardian module.
    Passing these checks does NOT mean the action is safe —
    AI still evaluates for scope, phishing, hallucination, etc.

    Note:
        These constraints are also path-oriented today (`allowed_paths`,
        `target_path`). That matches file deletion well, but it does not map
        cleanly onto non-file destructive actions like ``DELETE_EVENT``.
        Until the deletion-domain contract is generalized, those actions may
        fail at the Actor schema boundary before policy evaluation even starts.

    Path-vocabulary warning:
        ``allowed_paths`` uses raw string matching against the action's
        ``target_path`` (see
        :meth:`intentframe_action_bundle.deletion.bundle.DeletionDomainBundle._path_matches`).
        It is **vocabulary-blind** — ``fnmatch`` / ``startswith`` never
        applies ``normalize_virtual_path`` or ``canonicalize_real_path``.
        Because a single :class:`DeletionConstraints` instance is shared
        across every ``DELETE_*`` action a user is granted (it is keyed
        by :class:`DomainType`, not by action category), mixing virtual
        (``/home/*``) and real-path (``~/Documents/*``) patterns in the
        same list can only work by coincidence (disjoint namespaces).

        Recommended: populate ``allowed_paths`` only when the user's
        deletion allowlist stays within a single vocabulary.  If both
        ``DELETE_FILE`` and ``DELETE_HOST_FILE`` are granted, leave
        ``allowed_paths = None`` and rely on per-action
        :class:`FileConstraints` / :class:`HostFileConstraints` plus the
        Deterministic Guardian floor (``delete_host_file_floor``) to
        carry the path-vocabulary load.
    """

    domain: Literal[DomainType.DELETION] = DomainType.DELETION
    require_confirmation: bool = True
    allowed_paths: Optional[list[str]] = None
    block_irreversible: bool = False
