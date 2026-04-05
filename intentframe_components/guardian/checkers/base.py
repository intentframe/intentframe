"""Base class for Guardian constraint checkers.

Mirrors the DomainModule pattern from guardian/domains/.
Each checker pairs with a constraint data model — it owns
the deterministic check logic and the AI-facing summary.

A checker can BLOCK on constraint violations. It cannot ALLOW.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from intentframe_core.types import IntentFrame


class ConstraintChecker(ABC):
    """Pairs with a constraint data model. Owns checking + AI presentation."""

    @abstractmethod
    def check(self, intent: IntentFrame, constraints) -> tuple[bool, str]:
        """Deterministic constraint check.

        Returns:
            (True, "")      if no violation was found.
            (False, reason)  if the constraint is violated.
        """
        ...

    @abstractmethod
    def summarize(self, constraints) -> str:
        """Return a concise AI-facing summary of these constraints.

        Must not leak large data (resolved contact lists, etc.).
        Should include fields useful for semantic reasoning
        (amount caps, path patterns, etc.).
        """
        ...
