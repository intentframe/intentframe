"""DomainBundle base class — cross-action deterministic structural enforcement.

Domain bundles do not know action ids; routing is declared separately via
``register_domain_routes``. Hooks take opaque ``domain_constraints`` dict slices.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from intentframe_bundle_sdk.types import BundlePhaseOutcome

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame


class DomainBundle(ABC):
    """Deterministic domain enforcement — BLOCK or pass, never ALLOW."""

    bundle_id: str
    domain_id: str

    def validate(self, domain_constraints: dict[str, Any] | None) -> None:
        """Startup-only validation of policy YAML shape for this domain."""
        if domain_constraints is not None:
            raise NotImplementedError(
                f"domain bundle {self.bundle_id!r} must override validate"
            )

    def enforce(
        self,
        intent: IntentFrame,
        domain_constraints: dict[str, Any] | None,
    ) -> BundlePhaseOutcome:
        del intent, domain_constraints
        raise NotImplementedError(
            f"domain bundle {self.bundle_id!r} must override enforce"
        )

    def describe(self, domain_constraints: dict[str, Any] | None) -> str | None:
        del domain_constraints
        return None
