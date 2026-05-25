"""ActionBundle base class — hooks only; order owned by DeterministicRunner.

Bundles never receive ``UserContext`` or ``UserPolicy``. Hooks take a deep-copied
per-action :class:`ActionPermission` with opaque ``constraints`` dicts.

Resource lifecycle:

- Bundles that open external handles (DB clients, pools, background tasks) must
  own them as **instance state** and release them in :meth:`aclose`.
- Default :meth:`startup` / :meth:`aclose` are no-ops; the runtime calls
  :func:`intentframe_bundle_sdk.lifecycle.startup_bundles` /
  :func:`intentframe_bundle_sdk.lifecycle.shutdown_bundles` on boot/shutdown.
- Do **not** use module-level singletons for clients.

Future extension (not implemented): if a bundle owns many disposables, consider
registering them on an ``asyncio.AsyncExitStack`` inside :meth:`startup` and
awaiting ``stack.aclose()`` from :meth:`aclose`, or a host-provided
``add_shutdown_hook()`` helper — only when multiple resources per bundle appear.
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

    def onboarding_guardrails(self) -> str:
        """Paste-ready markdown for the onboarding system-prompt middle section."""
        return ""

    async def startup(self) -> None:
        """Optional one-shot init after registration. Must be idempotent."""
        return None

    async def aclose(self) -> None:
        """Optional resource release on shutdown. Must be idempotent."""
        return None
