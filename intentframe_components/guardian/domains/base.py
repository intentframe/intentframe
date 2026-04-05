"""Base class for Guardian domain modules."""

from __future__ import annotations

from abc import ABC, abstractmethod

from action_registry.types import DomainType
from intentframe_core.types import IntentFrame
from policy_registry.domains.base import DomainConstraints


class DomainModule(ABC):
    """Deterministic enforcer for a critical domain.

    Can BLOCK on structural violations (amount > limit, path not allowed).
    Cannot ALLOW — passing the check only means "no structural violation."
    """

    @property
    @abstractmethod
    def domain(self) -> DomainType: ...

    @abstractmethod
    def check(
        self,
        intent: IntentFrame,
        constraints: DomainConstraints,
    ) -> tuple[bool, str]:
        """Run structural checks against the intent.

        Returns:
            (True, "")  if no structural violation was found.
            (False, reason) if a structural violation was detected.
        """
        ...
