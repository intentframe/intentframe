"""DomainBundle base class — cross-action deterministic structural enforcement."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from intentframe_bundle_sdk.types import BundlePhaseOutcome

if TYPE_CHECKING:
    from action_registry.types import DomainType
    from intentframe_core.types import IntentFrame


class DomainBundle(ABC):
    """Deterministic domain enforcement — BLOCK or pass, never ALLOW."""

    bundle_id: str
    domain_type: DomainType

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
