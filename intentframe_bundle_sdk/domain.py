"""DomainBundle base class — cross-action deterministic structural enforcement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame
    from intentframe_bundle_sdk.types import BundleContext


class DomainBundle(ABC):
    """Deterministic domain enforcement — BLOCK or pass, never ALLOW.

    Domain bundles own constraint schema and check logic only.
    Action routing is declared separately via :func:`register_domain_routes`.
    """

    domain_id: str

    def validate_constraints(self, constraints: dict[str, Any]) -> None:
        """Optional startup validation of policy YAML shape for this domain."""

    @abstractmethod
    def check_domain(
        self,
        intent: IntentFrame,
        constraints: Any | None,
        ctx: BundleContext,
    ) -> tuple[bool, str]:
        """Return (True, '') if no violation, else (False, reason)."""

    def summarize_constraints(self, constraints: Any) -> str:
        """Human-readable summary for onboarding / AI prompts."""
        return str(constraints)
