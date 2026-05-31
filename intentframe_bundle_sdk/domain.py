"""DomainBundle base class — cross-action deterministic structural enforcement.

Domain bundles do not know action ids; routing is declared separately via
``register_domain_routes``. Hooks take opaque ``domain_constraints`` dict slices.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome
from intentframe_core.domains.base import DomainSchema

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame


class DomainBundle(ABC):
    """Deterministic domain enforcement — BLOCK or pass, never ALLOW."""

    bundle_id: str
    domain_id: str
    intent_schema: type[DomainSchema]

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

    async def startup(self) -> None:
        """Optional one-shot init after registration. Must be idempotent."""
        return None

    async def aclose(self) -> None:
        """Optional resource release on shutdown. Must be idempotent."""
        return None


def check_domain_intent_shape(
    bundle: DomainBundle,
    intent: IntentFrame,
) -> BundlePhaseOutcome:
    """Framework-owned domain intent schema check before author enforcement.

    This intentionally mirrors Actor validation: domain schemas validate the
    raw ``IntentFrame.data`` payload, not a bundle-normalized projection from
    other IntentFrame fields such as ``target``.
    """
    ctx = BundleContext(intent=intent.model_copy(deep=True))
    schema = getattr(bundle, "intent_schema", None)
    if schema is None:
        return BundlePhaseOutcome.block(
            ctx,
            reason=f"domain {bundle.domain_id!r}: no intent_schema declared",
            matched_gate="domain_schema",
        )
    try:
        schema.model_validate(intent.data or {})
    except Exception as exc:
        return BundlePhaseOutcome.block(
            ctx,
            reason=(
                f"Domain violation ({bundle.domain_id}): "
                f"invalid intent shape: {exc}"
            ),
            matched_gate="domain_schema",
        )
    return BundlePhaseOutcome.continue_(ctx)
