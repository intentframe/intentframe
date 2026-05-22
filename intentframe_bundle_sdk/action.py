"""ActionBundle base class — hooks only; order owned by DeterministicRunner."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from intentframe_bundle_sdk.types import (
    AnalysisContext,
    BundleContext,
    BundleDeterministicResult,
    BundlePhaseOutcome,
    PhaseDecision,
)

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame


class ActionBundle(ABC):
    """Governed lifecycle hooks — ``DeterministicRunner`` enforces order.

    Phases authors may implement:

        prepare_evidence()  — shield / file_intel; may BLOCK (never ALLOW)
        enrich()            — resolve opaque ids → ``enriched_intent``; never BLOCK
        check_policy()      — YAML constraints; BLOCK only (SDK default)
        structural_gates()  — family BLOCK floors
        allow_gates()       — conditional ALLOW short-circuits

    Domain checks run in the runner between check_policy and structural_gates.
    """

    bundle_id: str
    action_ids: frozenset[str] = frozenset()
    constraint_type: type | None = None

    async def run_deterministic(
        self,
        intent: IntentFrame,
        permission,
        *,
        verbose: bool = False,
        user_context=None,
    ) -> BundleDeterministicResult:
        """Deprecated direct entry — prefer DeterministicRunner.run_action_bundle."""
        from intentframe_bundle_sdk.runner import DeterministicRunner

        if user_context is None:
            raise TypeError(
                "run_deterministic requires user_context; "
                "use DeterministicRunner.run_action_bundle"
            )
        return await DeterministicRunner.run_action_bundle(
            self,
            intent,
            permission,
            user_context,
            verbose=verbose,
        )

    async def prepare_evidence(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        """Collect deterministic evidence (command_shield, file_intel). May BLOCK."""
        del intent, permission, verbose
        return BundlePhaseOutcome.continue_(ctx)

    async def enrich(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        """Resolve opaque ids into ``ctx.enriched_intent``. Must not BLOCK or ALLOW."""
        del intent, permission, verbose
        return BundlePhaseOutcome.continue_(ctx)

    def check_policy(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        if permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)

        from intentframe_components.guardian.checkers import CheckContext, CONSTRAINT_CHECKERS

        checker = CONSTRAINT_CHECKERS.get(type(permission.constraints))
        if checker is None:
            return BundlePhaseOutcome.continue_(ctx)

        check_ctx = CheckContext(
            command_intel=ctx.command_intel,
            file_intel=ctx.file_intel,
        )
        passed, reason = checker.check(
            ctx.effective_intent,
            permission.constraints,
            check_ctx,
        )
        if not passed:
            return BundlePhaseOutcome.block(
                ctx,
                reason=f"Constraint violation: {reason}",
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    def structural_gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        del intent, permission
        return BundlePhaseOutcome.continue_(ctx)

    def allow_gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        del intent, permission
        return BundlePhaseOutcome.continue_(ctx)

    def gates(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome:
        """Backward compat — delegates to allow_gates."""
        return self.allow_gates(intent, permission, ctx)

    def build_analysis_context(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> AnalysisContext:
        del intent, permission
        return AnalysisContext(
            command_intel=ctx.command_intel,
            file_intel=ctx.file_intel,
            terminal_command_signals=ctx.terminal_command_signals,
        )

    @staticmethod
    def _phase_to_result(phase: BundlePhaseOutcome) -> BundleDeterministicResult:
        if phase.decision is PhaseDecision.BLOCK:
            decision_path = (
                "command_shield"
                if phase.matched_gate == "command_shield"
                else "deterministic"
            )
            return BundleDeterministicResult(
                decision="BLOCK",
                context=phase.context,
                reason=phase.reason,
                matched_gate=phase.matched_gate,
                decision_path=decision_path,
            )
        return BundleDeterministicResult(
            decision="ALLOW",
            context=phase.context,
            reason=phase.reason,
            matched_gate=phase.matched_gate,
        )


class NullActionBundle(ActionBundle):
    """No-op bundle for actions without a registered family."""

    bundle_id = "null"
    action_ids = frozenset()


class CheckerOnlyActionBundle(ActionBundle):
    """Policy checker only — no evidence or enrichment hooks."""

    def __init__(self, bundle_id: str, constraint_type: type) -> None:
        self.bundle_id = bundle_id
        self.constraint_type = constraint_type
