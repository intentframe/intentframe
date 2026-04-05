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
    """

    domain: Literal[DomainType.DELETION] = DomainType.DELETION
    require_confirmation: bool = True
    allowed_paths: Optional[list[str]] = None
    block_irreversible: bool = False
