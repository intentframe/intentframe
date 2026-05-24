"""Layer 4 — Deterministic Guardian (pre-AE pass)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from intentframe_action_bundle import _ensure_first_party_bundles_loaded
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext
from intentframe_core.types import IntentFrame, UserContext


class DeterministicDecision(str, Enum):
    """Outcome of the pre-AE deterministic pass."""

    BLOCK = "BLOCK"
    ALLOW = "ALLOW"
    UNDECIDED = "UNDECIDED"


@dataclass(frozen=True)
class DeterministicResult:
    """Decision + audit metadata + bundle context for AI path."""

    decision: DeterministicDecision
    reason: str = ""
    matched_gate: str = ""
    decision_path: str = "deterministic"
    bundle_context: BundleContext | None = None
    bundle_ai_context: BundleAIContext | None = None
    dg_exception: str = ""


class DeterministicGuardian:
    """Pre-AE deterministic stage — permission + DeterministicRunner."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        _ensure_first_party_bundles_loaded()

    async def decide_async(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        *,
        verbose: bool | None = None,
    ) -> DeterministicResult:
        if verbose is None:
            verbose = self.verbose

        try:
            return await self._decide_inner(
                intent,
                user_context,
                verbose=verbose,
            )
        except Exception as exc:  # noqa: BLE001
            exc_repr = repr(exc)
            if verbose:
                print(f"    │  DG exception: {exc_repr} — BLOCK (fail-closed)")
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=f"deterministic guardian error: {exc_repr}",
                matched_gate="exception",
                decision_path="deterministic",
                dg_exception=exc_repr,
            )

    async def _decide_inner(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        *,
        verbose: bool,
    ) -> DeterministicResult:
        action = intent.action.value

        if action not in user_context.allowed_actions:
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=f"Action '{action}' is not permitted by user policy",
                matched_gate="permission",
            )

        permission = user_context.allowed_actions[action]
        bundle = action_bundle_for(action)
        if bundle is None:
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=f"No registered bundle for allowed action '{action}'",
                matched_gate="no_bundle",
            )

        bundle_result = await DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
            verbose=verbose,
        )
        ctx = bundle_result.context
        intent = ctx.effective_intent

        if bundle_result.decision == "BLOCK":
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=bundle_result.reason,
                matched_gate=bundle_result.matched_gate,
                decision_path=bundle_result.decision_path,
                bundle_context=ctx,
            )
        if bundle_result.decision == "ALLOW":
            return DeterministicResult(
                decision=DeterministicDecision.ALLOW,
                reason=bundle_result.reason,
                matched_gate=bundle_result.matched_gate,
                decision_path=bundle_result.decision_path,
                bundle_context=ctx,
            )

        return DeterministicResult(
            decision=DeterministicDecision.UNDECIDED,
            matched_gate="undecided",
            bundle_context=ctx,
            bundle_ai_context=bundle_result.bundle_ai_context,
        )


__all__ = [
    "DeterministicDecision",
    "DeterministicGuardian",
    "DeterministicResult",
]
