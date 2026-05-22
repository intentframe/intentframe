"""DomainBundle base class — cross-action deterministic structural enforcement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from action_registry.types import DomainType
    from intentframe_core.types import IntentFrame, UserContext


class DomainBundle(ABC):
    """Deterministic domain enforcement — BLOCK or pass, never ALLOW."""

    domain_id: str
    action_ids: frozenset[str]

    @property
    @abstractmethod
    def domain_type(self) -> DomainType:
        ...

    @abstractmethod
    def check(
        self,
        intent: IntentFrame,
        user_context: UserContext,
    ) -> tuple[bool, str]:
        """Return (True, '') if no violation, else (False, reason)."""
        ...
