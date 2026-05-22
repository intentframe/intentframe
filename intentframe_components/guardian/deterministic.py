"""Layer 4 — Deterministic Guardian (pre-AE pass).

Substrate permission gate + :class:`DeterministicRunner` (Bundle SDK).

Fixed order (legacy 66e567c, permission-first):

    1. Permission (substrate)
    2. prepare_evidence → enrich → check_policy → domain → structural → allow
    3. UNDECIDED → AI path

Authors implement bundle hooks only; they do not choose global order.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.runner import DeterministicRunner
from intentframe_bundle_sdk.types import AnalysisContext, BundleContext
from intentframe_core.types import (
    CommandIntel,
    ExecutionContext,
    IntentFrame,
    UserContext,
)


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
    analysis_context: AnalysisContext | None = None


class DeterministicGuardian:
    """Pre-AE deterministic stage — permission + DeterministicRunner."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        from intentframe_action_bundle.bundles.register import ensure_bundles_registered

        ensure_bundles_registered()

    def decide(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        active_domains: Optional[set[str]] = None,
        execution_context: Optional[ExecutionContext] = None,
        command_intel: Optional[CommandIntel] = None,
    ) -> DeterministicResult:
        """Sync wrapper for tests — runs async lifecycle in a fresh loop."""
        del active_domains, execution_context
        return asyncio.run(
            self.decide_async(
                intent,
                user_context,
                verbose=self.verbose,
                command_intel=command_intel,
            )
        )

    async def decide_async(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        *,
        verbose: bool | None = None,
        command_intel: Optional[CommandIntel] = None,
    ) -> DeterministicResult:
        if verbose is None:
            verbose = self.verbose

        try:
            return await self._decide_inner(
                intent,
                user_context,
                verbose=verbose,
                command_intel=command_intel,
            )
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"    │  DG exception: {exc!r} — UNDECIDED")
            return DeterministicResult(
                decision=DeterministicDecision.UNDECIDED,
                reason=f"deterministic guardian error: {exc!r}",
                matched_gate="exception",
            )

    async def _decide_inner(
        self,
        intent: IntentFrame,
        user_context: UserContext,
        *,
        verbose: bool,
        command_intel: Optional[CommandIntel] = None,
    ) -> DeterministicResult:
        action = intent.action.value

        if action not in user_context.allowed_actions:
            return DeterministicResult(
                decision=DeterministicDecision.BLOCK,
                reason=f"Action '{action}' is not permitted by user policy",
                matched_gate="permission",
            )

        permission = user_context.allowed_actions[action]
        bundle = action_bundle_for(action, permission)

        bundle_result = await DeterministicRunner.run_action_bundle(
            bundle,
            intent,
            permission,
            user_context,
            verbose=verbose,
            command_intel=command_intel,
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
                bundle_context=ctx,
            )

        analysis_ctx = bundle.build_analysis_context(intent, permission, ctx)

        return DeterministicResult(
            decision=DeterministicDecision.UNDECIDED,
            matched_gate="undecided",
            bundle_context=ctx,
            analysis_context=analysis_ctx,
        )


from intentframe_action_bundle.passive_read.actions import PASSIVE_READ_ACTIONS

_PRE_AE_SAFE_READS: frozenset[str] = PASSIVE_READ_ACTIONS

from intentframe_action_bundle.terminal._read_only import (
    READ_ONLY_INCOMPATIBLE as _READ_ONLY_INCOMPATIBLE,
    is_read_only_fast_path,
)


__all__ = [
    "DeterministicDecision",
    "DeterministicGuardian",
    "DeterministicResult",
    "_PRE_AE_SAFE_READS",
    "_READ_ONLY_INCOMPATIBLE",
    "is_read_only_fast_path",
]
