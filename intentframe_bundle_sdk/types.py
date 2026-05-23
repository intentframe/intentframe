"""Shared types for the Bundle SDK lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from intentframe_core.types import IntentFrame


class PhaseDecision(str, Enum):
    """Outcome of a single bundle lifecycle phase."""

    CONTINUE = "CONTINUE"
    BLOCK = "BLOCK"
    ALLOW = "ALLOW"


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
    # Set when permission.constraints is present but CONSTRAINT_CHECKERS has no entry
    # (e.g. CalendarConstraints). Does not BLOCK — see constraint_checker_skip.py.
    constraint_checker_skipped: str | None = None

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

    def constraint_checker_audit_fields(self) -> dict[str, object]:
        """Audit when YAML constraints were not checked deterministically."""
        if not self.constraint_checker_skipped:
            return {}
        return {"constraint_checker_skipped": self.constraint_checker_skipped}


@dataclass
class BundleAIContext:
    """Bundle-supplied AI prompt material for the UNDECIDED path."""

    ae_system_instructions: str | None = None
    ae_external_context: str = ""
    guardian_system_instructions: str | None = None
    guardian_external_context: str = ""
    ae_prompt_label: str | None = None
    guardian_prompt_label: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


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
    """Merge enrichment + constraint-checker skip fields into pipeline audit dicts."""
    if ctx is None:
        return {}
    return {
        **ctx.enrichment_audit_fields(),
        **ctx.constraint_checker_audit_fields(),
    }


@dataclass(frozen=True)
class BundlePhaseOutcome:
    """Result of prepare / check_policy / gates."""

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


@dataclass(frozen=True)
class BundleDeterministicResult:
    """Full action-bundle deterministic outcome + context for AI path."""

    decision: str  # BLOCK | ALLOW | UNDECIDED
    context: BundleContext
    reason: str = ""
    matched_gate: str = ""
    decision_path: str = "deterministic"
