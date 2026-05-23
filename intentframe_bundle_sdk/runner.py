"""Host-only deterministic orchestration — fixed gate order (authors do not override).

After permission (DeterministicGuardian):

    snapshot submitted intent (``model_copy``)
    prepare_evidence()     — shield / file_intel; may BLOCK
    enrich()               — resolve opaque ids; never BLOCK
    record_enrichment()    — host ledger
    check_policy()         — YAML constraints
    domain()               — cross-action BLOCK only
    structural_gates()     — family BLOCK floors
    passive_read ALLOW     — SDK standard safe-read fast path
    allow_gates()          — plugin-specific ALLOW
    UNDECIDED → AI path
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from action_registry.types import ACTION_DOMAINS
from intentframe_bundle_sdk.registry import action_bundle_for, domain_bundle_for
from intentframe_bundle_sdk.types import (
    BundleContext,
    BundleDeterministicResult,
    BundlePhaseOutcome,
    record_enrichment,
)

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame, UserContext


class DeterministicRunner:
    """Runs the governed action + domain lifecycle; bundles supply hooks only."""

    @classmethod
    async def run_action_bundle(
        cls,
        bundle,
        intent: IntentFrame,
        permission,
        user_context: UserContext,
        *,
        verbose: bool = False,
    ) -> BundleDeterministicResult:
        """Execute evidence → enrich → policy → domain → structural → allow."""
        ctx = BundleContext(intent=intent.model_copy(deep=True))

        evidence = await bundle.prepare_evidence(
            intent, permission, ctx, verbose=verbose
        )
        if evidence.terminal:
            return bundle._phase_to_result(evidence)
        ctx = evidence.context

        enriched = await bundle.enrich(intent, permission, ctx, verbose=verbose)
        if enriched.terminal:
            raise RuntimeError(
                f"bundle {bundle.bundle_id!r} enrich() returned terminal "
                f"{enriched.decision.value} — enrichment must not BLOCK or ALLOW"
            )
        ctx = enriched.context
        record_enrichment(ctx, bundle_id=bundle.bundle_id)

        pol = bundle.check_policy(intent, permission, ctx, verbose=verbose)
        if pol.terminal:
            return bundle._phase_to_result(pol)
        ctx = pol.context

        domain_outcome = cls._run_domain(intent, user_context, ctx)
        if domain_outcome is not None:
            return domain_outcome

        struct = bundle.structural_gates(intent, permission, ctx)
        if struct.terminal:
            return bundle._phase_to_result(struct)
        ctx = struct.context

        passive = cls._try_passive_read_allow(bundle, intent, permission, ctx)
        if passive is not None:
            return bundle._phase_to_result(passive)

        allow = bundle.allow_gates(intent, permission, ctx)
        if allow.terminal:
            return bundle._phase_to_result(allow)

        return BundleDeterministicResult(decision="UNDECIDED", context=ctx)

    @staticmethod
    def _run_domain(
        intent: IntentFrame,
        user_context: UserContext,
        ctx: BundleContext,
    ) -> BundleDeterministicResult | None:
        domain_type = ACTION_DOMAINS.get(intent.action)
        if domain_type is None:
            return None
        domain_bundle = domain_bundle_for(domain_type.value)
        if domain_bundle is None:
            return None
        passed, reason = domain_bundle.check(ctx.effective_intent, user_context)
        if passed:
            return None
        return BundleDeterministicResult(
            decision="BLOCK",
            context=ctx,
            reason=f"Domain violation ({domain_type.value}): {reason}",
            matched_gate="domain",
        )

    @staticmethod
    def resolve_bundle(action_id: str, permission) -> object:
        return action_bundle_for(action_id, permission)

    @staticmethod
    def _try_passive_read_allow(
        bundle,
        intent: IntentFrame,
        permission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome | None:
        """IntentFrame-wide safe passive-read ALLOW (legacy step 4)."""
        action = intent.action.value
        if action not in bundle.passive_read_action_ids:
            return None
        if not permission.safe:
            return None
        return BundlePhaseOutcome.allow(
            ctx,
            reason=f"Permitted (deterministic: passive read): {action}",
            matched_gate="passive_read",
        )
