"""Shared types for the Bundle SDK lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from intentframe_core.types import IntentSignal, IntentFrame

# Bump this whenever the hook contract changes in a backwards-incompatible way
# (new required args, removed hooks, semantic shifts).  Bundles that declare
# ``min_sdk_version`` will fail at load time when this is below their minimum.
BUNDLE_SDK_VERSION: int = 2


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class BundleError(Exception):
    """Base class for all structured bundle errors."""


class BundleConfigError(BundleError):
    """Raised during startup / validate_constraints for configuration problems.
    Maps to a BLOCK at boot; the bundle is not registered.
    """


class BundleHookTimeout(BundleError):
    """Raised by the runner when a hook exceeds its deadline.
    Maps to a fail-closed BLOCK with matched_gate='hook_timeout'.
    """

    def __init__(self, bundle_id: str, hook: str, timeout_s: float) -> None:
        super().__init__(
            f"bundle {bundle_id!r} hook {hook!r} timed out after {timeout_s:.1f}s"
        )
        self.bundle_id = bundle_id
        self.hook = hook
        self.timeout_s = timeout_s


class BundleHookCrashed(BundleError):
    """Raised by the runner when a hook raises an unexpected exception.
    Wraps the original; maps to a fail-closed BLOCK with matched_gate='hook_crash'.
    """

    def __init__(self, bundle_id: str, hook: str, cause: BaseException) -> None:
        super().__init__(
            f"bundle {bundle_id!r} hook {hook!r} crashed: {cause!r}"
        )
        self.bundle_id = bundle_id
        self.hook = hook
        self.cause = cause
        self.__cause__ = cause


class PhaseDecision(str, Enum):
    """Outcome of a single bundle lifecycle phase."""

    CONTINUE = "CONTINUE"
    BLOCK = "BLOCK"
    ALLOW = "ALLOW"


class BundleGateDecision(str, Enum):
    """Terminal gate decision used by family structural helpers."""

    BLOCK = "BLOCK"
    ALLOW = "ALLOW"


@dataclass(frozen=True)
class ActionPermission:
    """Per-action policy slice passed to bundle hooks (opaque constraints dict)."""

    safe: bool
    constraints: dict[str, Any] | None = None

    def copy_with_constraints(
        self, constraints: dict[str, Any] | None
    ) -> ActionPermission:
        return ActionPermission(safe=self.safe, constraints=constraints)


def action_permission_from_policy(permission: Any) -> ActionPermission:
    """Convert a policy-registry permission into the SDK shape."""
    constraints = permission.constraints
    if constraints is not None and not isinstance(constraints, dict):
        constraints = constraints.model_dump(mode="python")
    return ActionPermission(safe=permission.safe, constraints=constraints)


@dataclass(frozen=True)
class EnrichmentRecord:
    """Host-written ledger when a bundle mutates intent via enrichment."""

    applied: bool
    bundle_id: str
    target_submitted: str = ""
    target_after: str = ""


@dataclass
class BundleContext:
    """Mutable lifecycle context passed through action-bundle phases."""

    intent: IntentFrame
    evidence: dict[str, Any] = field(default_factory=dict)
    enriched_intent: IntentFrame | None = None
    enrichment: EnrichmentRecord | None = None

    @property
    def intent_submitted(self) -> IntentFrame:
        """Agent-submitted frame frozen at runner entry (``intent`` field)."""
        return self.intent

    @property
    def effective_intent(self) -> IntentFrame:
        return self.enriched_intent or self.intent

    def enrichment_audit_fields(self) -> dict[str, object]:
        """Audit-only fields for pipeline ledger; empty when no enrichment."""
        if self.enrichment is None or not self.enrichment.applied:
            return {}
        return {
            "enrichment_applied": True,
            "enrichment_bundle_id": self.enrichment.bundle_id,
            "target_submitted": self.enrichment.target_submitted,
        }


@dataclass
class ConstraintPromptContext:
    """Runner-built constraint text for the UNDECIDED AI path."""

    action_constraints: str = "No specific constraints"
    domain_constraints: list[str] = field(default_factory=list)
    enforced_domains: list[str] = field(default_factory=list)


@dataclass
class BundleAIContext:
    """Bundle-supplied AI prompt material for the UNDECIDED path."""

    ae_system_instructions: str | None = None
    ae_external_context: str = ""
    guardian_system_instructions: str | None = None
    guardian_external_context: str = ""
    ae_prompt_label: str | None = None
    guardian_prompt_label: str | None = None
    constraint_context: ConstraintPromptContext | None = None
    ae_log_hints: tuple[str, ...] = field(default_factory=tuple)
    ae_intent_signals: tuple[IntentSignal, ...] = field(default_factory=tuple)
    ae_signal_truncated: bool = False


def bundle_ai_context_or_empty(
    bundle_ai_context: BundleAIContext | None,
) -> BundleAIContext:
    return bundle_ai_context if bundle_ai_context is not None else BundleAIContext()


def enrichment_changed(submitted: IntentFrame, effective: IntentFrame) -> bool:
    """True when enrichment altered target or data (host detection)."""
    if submitted.target != effective.target:
        return True
    return (submitted.data or {}) != (effective.data or {})


def record_enrichment(
    ctx: BundleContext,
    *,
    bundle_id: str,
) -> None:
    """Populate host enrichment ledger after bundle ``enrich()``."""
    effective = ctx.effective_intent
    if not enrichment_changed(ctx.intent, effective):
        ctx.enrichment = None
        return
    ctx.enrichment = EnrichmentRecord(
        applied=True,
        bundle_id=bundle_id,
        target_submitted=str(ctx.intent.target or ""),
        target_after=str(effective.target or ""),
    )


def enrichment_audit_fields(ctx: BundleContext | None) -> dict[str, object]:
    """Merge enrichment fields into pipeline audit dicts."""
    if ctx is None:
        return {}
    return ctx.enrichment_audit_fields()


@dataclass(frozen=True)
class BundlePhaseOutcome:
    """Result of a bundle lifecycle phase."""

    decision: PhaseDecision
    context: BundleContext
    reason: str = ""
    matched_gate: str = ""

    @classmethod
    def continue_(cls, ctx: BundleContext) -> BundlePhaseOutcome:
        return cls(decision=PhaseDecision.CONTINUE, context=ctx)

    @classmethod
    def block(cls, ctx: BundleContext, *, reason: str, matched_gate: str) -> BundlePhaseOutcome:
        return cls(
            decision=PhaseDecision.BLOCK,
            context=ctx,
            reason=reason,
            matched_gate=matched_gate,
        )

    @classmethod
    def allow(cls, ctx: BundleContext, *, reason: str, matched_gate: str) -> BundlePhaseOutcome:
        return cls(
            decision=PhaseDecision.ALLOW,
            context=ctx,
            reason=reason,
            matched_gate=matched_gate,
        )

    @property
    def terminal(self) -> bool:
        return self.decision in (PhaseDecision.BLOCK, PhaseDecision.ALLOW)

    def to_deterministic_result(self) -> BundleDeterministicResult:
        if self.decision is PhaseDecision.BLOCK:
            decision_path = self.matched_gate if self.matched_gate else "deterministic"
            return BundleDeterministicResult(
                decision="BLOCK",
                context=self.context,
                reason=self.reason,
                matched_gate=self.matched_gate,
                decision_path=decision_path,
            )
        if self.decision is PhaseDecision.ALLOW:
            return BundleDeterministicResult(
                decision="ALLOW",
                context=self.context,
                reason=self.reason,
                matched_gate=self.matched_gate,
                decision_path=self.matched_gate if self.matched_gate else "deterministic",
            )
        raise ValueError(
            f"to_deterministic_result() requires BLOCK or ALLOW, got {self.decision!r}"
        )


@dataclass(frozen=True)
class BundleDeterministicResult:
    """Full action-bundle deterministic outcome + context for AI path."""

    decision: str  # BLOCK | ALLOW | UNDECIDED
    context: BundleContext
    reason: str = ""
    matched_gate: str = ""
    decision_path: str = "deterministic"
    bundle_ai_context: BundleAIContext | None = None
    dg_exception: str = ""
