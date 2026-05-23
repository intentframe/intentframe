"""ActionBundle base class — hooks only; order owned by DeterministicRunner.

Plugin layout conventions (first-party pattern):

- One code folder per action family (``terminal/``, ``files/``, ``email/``, …).
- Each family owns its action ids, constraint schema, evidence keys, gates,
  and AI context. Register via ``register_action_bundle`` (loader in PR B).
- Cross-family reuse is by explicit import between plugin packages (e.g.
  ``host_files`` imports write tooling from ``files``). The SDK does not
  provide a shared-kit module today; if multiple third-party plugins need
  the same primitives, extract a neutral helper package both depend on.
- SDK-standard behavior (fixed gate order, ``passive_read_action_ids``) lives
  in ``DeterministicRunner`` — families declare eligibility, not enforcement.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from intentframe_action_bundle.evidence import CommandIntel, FileIntel
from intentframe_bundle_sdk.types import (
    BundleAIContext,
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
        (runner) passive-read ALLOW — SDK standard fast path when
            ``action in passive_read_action_ids`` and ``permission.safe``
        allow_gates()       — plugin-specific ALLOW short-circuits
        build_ai_context()  — optional AE/Guardian prompt material for UNDECIDED

    Domain checks run in the runner between check_policy and structural_gates.
    """

    bundle_id: str
    action_ids: frozenset[str] = frozenset()
    passive_read_action_ids: frozenset[str] = frozenset()
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
        """Collect deterministic evidence. May BLOCK."""
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
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        if permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)

        from intentframe_components.guardian.checkers import CheckContext, CONSTRAINT_CHECKERS
        from intentframe_bundle_sdk.constraint_checker_skip import (
            note_missing_constraint_checker,
        )

        constraint_type = type(permission.constraints)
        checker = CONSTRAINT_CHECKERS.get(constraint_type)
        if checker is None:
            note_missing_constraint_checker(
                ctx,
                constraint_type,
                phase="deterministic_check_policy",
                verbose=verbose,
            )
            return BundlePhaseOutcome.continue_(ctx)

        command_intel = ctx.evidence.get("command_intel")
        file_intel = ctx.evidence.get("file_intel")
        if command_intel is not None and not isinstance(command_intel, CommandIntel):
            command_intel = None
        if file_intel is not None and not isinstance(file_intel, FileIntel):
            file_intel = None

        check_ctx = CheckContext(
            command_intel=command_intel,
            file_intel=file_intel,
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

    def build_ai_context(
        self,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundleAIContext:
        """Return bundle-owned AI prompt material; default is substrate standard only."""
        del intent, permission, ctx
        return BundleAIContext()

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
