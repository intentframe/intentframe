"""ActionBundle base class — hooks only; order owned by DeterministicRunner.

Bundles never receive ``UserContext`` or ``UserPolicy``. Hooks take a deep-copied
per-action :class:`ActionPermission` with opaque ``constraints`` dicts.

## Async contract

All hooks that touch policy, constraints, or external services are ``async``.
This keeps the signature forward-compatible with out-of-process transports
(MCP stdio sidecar, gRPC plugin) where every call is inherently async.

    Sync (no I/O, always fast):
        validate_constraints    — startup schema validation only
        onboarding_guardrails   — returns static text

    Async (may do I/O; runner enforces a per-hook deadline):
        prepare_evidence        — may call pre-pipeline classifiers
        enrich                  — may enrich intent from external data
        enforce_constraints     — may call auth services, resolve dynamic ACLs
        structural_gates        — may consult path/floor registries
        allow_gates             — may verify fast-path conditions externally
        build_ai_context        — may fetch context from external sources
        describe_constraints    — may resolve dynamic list sizes for display

## Resource lifecycle

- Bundles that open external handles (DB clients, pools, background tasks) must
  own them as **instance state** and release them in :meth:`aclose`.
- Default :meth:`startup` / :meth:`aclose` are no-ops; the runtime calls
  :func:`intentframe_bundle_sdk.lifecycle.startup_bundles` /
  :func:`intentframe_bundle_sdk.lifecycle.shutdown_bundles` on boot/shutdown.
- Do **not** use module-level singletons for clients.

## Versioning

Declare ``min_sdk_version`` to fail fast when loaded against an older SDK::

    class MyBundle(ActionBundle):
        bundle_id = "my_bundle"
        min_sdk_version = 2          # requires BUNDLE_SDK_VERSION >= 2

## Runtime hint (forward-compatible)

``runtime`` declares where the bundle executes.  The runner currently only
supports ``"in_process"``.  Declaring a different value here is a no-op today
but reserves the field for future transport routing (MCP sidecar, gRPC plugin).
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Literal

from intentframe_bundle_sdk.types import (
    BUNDLE_SDK_VERSION,
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

    # Declare min SDK version required by this bundle.  Loader raises
    # ``BundleConfigError`` when ``BUNDLE_SDK_VERSION < min_sdk_version``.
    min_sdk_version: int = 1

    # Forward-compatible transport hint.  Only "in_process" is implemented.
    runtime: Literal["in_process"] = "in_process"

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
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        """Enrich the intent with context from external sources.

        Receives ``action_permission`` so that bundles can read constraint
        fields (e.g. dynamic source lists) without reaching into a context
        side-channel.  Must not BLOCK or ALLOW — return ``continue_`` always.
        """
        del intent, action_permission, verbose
        return BundlePhaseOutcome.continue_(ctx)

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        """Startup-only shape validation when policy declares constraints.

        Intentionally sync — runs once at boot against a Pydantic model, no I/O.
        Raise :class:`BundleConfigError` on invalid shape.
        """
        if action_permission.constraints is not None:
            raise NotImplementedError(
                f"bundle {self.bundle_id!r} must override validate_constraints"
            )

    async def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        """Enforce policy constraints, returning BLOCK or CONTINUE.

        Async so that implementations can call external services (auth,
        SCIM/LDAP group resolution, budget checks, ACL lookups, etc.)
        without blocking the event loop.
        """
        del intent, action_permission, ctx, verbose
        raise NotImplementedError(
            f"bundle {self.bundle_id!r} must override enforce_constraints"
        )

    async def structural_gates(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        """Path/floor BLOCKs that do not depend on the user's constraint dict."""
        del intent
        return BundlePhaseOutcome.continue_(ctx)

    async def allow_gates(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        """Fast-path ALLOW conditions (e.g. read-only terminal commands)."""
        del intent, action_permission
        return BundlePhaseOutcome.continue_(ctx)

    async def build_ai_context(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        """Assemble AI prompt material for the UNDECIDED path."""
        del intent, action_permission, ctx
        return BundleAIContext()

    async def describe_constraints(
        self, action_permission: ActionPermission
    ) -> str | None:
        """Human-readable constraint summary for Guardian prompts."""
        del action_permission
        return None

    def onboarding_guardrails(self) -> str:
        """Paste-ready markdown for the onboarding system-prompt middle section.

        Intentionally sync — returns static text, no I/O.
        """
        return ""

    async def startup(self) -> None:
        """Optional one-shot init after registration. Must be idempotent."""
        return None

    async def aclose(self) -> None:
        """Optional resource release on shutdown. Must be idempotent."""
        return None


def _check_sdk_version(bundle: ActionBundle) -> None:
    """Raise ``BundleConfigError`` if the bundle requires a newer SDK."""
    from intentframe_bundle_sdk.types import BundleConfigError

    if bundle.min_sdk_version > BUNDLE_SDK_VERSION:
        raise BundleConfigError(
            f"bundle {bundle.bundle_id!r} requires SDK version "
            f">= {bundle.min_sdk_version} but running {BUNDLE_SDK_VERSION}"
        )
