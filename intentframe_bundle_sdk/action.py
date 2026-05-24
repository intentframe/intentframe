"""ActionBundle base class — hooks only; order owned by DeterministicRunner.

Bundles never receive ``UserContext`` or ``UserPolicy``. Hooks take a deep-copied
per-action :class:`ActionPermission` with opaque ``constraints`` dicts.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleAIContext,
    BundleContext,
    BundlePhaseOutcome,
)

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame


class ActionBundle(ABC):
    """Governed lifecycle hooks — ``DeterministicRunner`` enforces order."""

    bundle_id: str
    action_ids: frozenset[str] = frozenset()
    passive_read_action_ids: frozenset[str] = frozenset()

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del intent, verbose
        return BundlePhaseOutcome.continue_(ctx)

    async def enrich(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del intent, verbose
        return BundlePhaseOutcome.continue_(ctx)

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        """Startup-only shape validation when policy declares constraints."""
        if action_permission.constraints is not None:
            raise NotImplementedError(
                f"bundle {self.bundle_id!r} must override validate_constraints"
            )

    def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del intent, action_permission, ctx, verbose
        raise NotImplementedError(
            f"bundle {self.bundle_id!r} must override enforce_constraints"
        )

    def structural_gates(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        del intent
        return BundlePhaseOutcome.continue_(ctx)

    def allow_gates(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        del intent, action_permission
        return BundlePhaseOutcome.continue_(ctx)

    def build_ai_context(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        del intent, action_permission, ctx
        return BundleAIContext()

    def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        del action_permission
        return None
