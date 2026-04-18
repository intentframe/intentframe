"""Base class for Guardian constraint checkers.

Mirrors the DomainModule pattern from guardian/domains/.
Each checker pairs with a constraint data model — it owns
the deterministic check logic and the AI-facing summary.

A checker can BLOCK on constraint violations. It cannot ALLOW.

``CheckContext`` carries additional deterministic facts a checker
may choose to consume — today just the CommandIntel side-channel
from command_shield (used by TerminalChecker for capability allow/
deny gating).  Keeping it in a single frozen dataclass means we can
grow the vocabulary without rippling through every checker signature.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from intentframe_core.types import CommandIntel, IntentFrame


@dataclass(frozen=True)
class CheckContext:
    """Immutable side-channel inputs for a constraint check.

    Extend this carefully: every new field is available to every
    checker implementation.  Keep additions to deterministic facts
    that originate upstream of Guardian's AI path (shield output,
    runtime privilege, active-domain set).  Never carry AI output
    here — that flows via ``AnalysisReport`` to keep the input/
    output surfaces distinct.
    """

    command_intel: CommandIntel | None = None


class ConstraintChecker(ABC):
    """Pairs with a constraint data model. Owns checking + AI presentation."""

    @abstractmethod
    def check(
        self,
        intent: IntentFrame,
        constraints,
        context: CheckContext | None = None,
    ) -> tuple[bool, str]:
        """Deterministic constraint check.

        ``context`` is additive: checkers that have nothing to gain
        from it should accept and ignore it.  ``None`` must always
        be a valid value — Phase-3 wiring passes an empty context
        for call paths that predate the field (e.g. tests).

        Returns:
            (True, "")       if no violation was found.
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
