"""Host-only deterministic orchestration — fixed gate order (authors do not override)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from action_registry.types import ACTION_DOMAINS

from intentframe_bundle_sdk.registry import domain_bundle_for
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleAIContext,
    BundleContext,
    BundleDeterministicResult,
    BundlePhaseOutcome,
    ConstraintPromptContext,
    action_permission_from_policy,
    record_enrichment,
)

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame, UserContext

    from intentframe_bundle_sdk.action import ActionBundle
    from intentframe_bundle_sdk.domain import DomainBundle


class DeterministicRunner:
    """Runs the governed action + domain lifecycle; bundles supply hooks only."""

    @classmethod
    async def run_action_bundle(
        cls,
        bundle: ActionBundle,
        intent: IntentFrame,
        permission: Any,
        user_context: UserContext,
        *,
        verbose: bool = False,
    ) -> BundleDeterministicResult:
        action_permission = action_permission_from_policy(permission)
        ctx = BundleContext(intent=intent.model_copy(deep=True))

        evidence = await bundle.prepare_evidence(intent, ctx, verbose=verbose)
        if evidence.terminal:
            return evidence.to_deterministic_result()
        ctx = evidence.context

        enriched = await bundle.enrich(intent, ctx, verbose=verbose)
        if enriched.terminal:
            raise RuntimeError(
                f"bundle {bundle.bundle_id!r} enrich() returned terminal "
                f"{enriched.decision.value} — enrichment must not BLOCK or ALLOW"
            )
        ctx = enriched.context
        record_enrichment(ctx, bundle_id=bundle.bundle_id)

        if action_permission.constraints is not None:
            frozen = action_permission.copy_with_constraints(
                deepcopy(action_permission.constraints)
            )
            try:
                pol = bundle.enforce_constraints(intent, frozen, ctx, verbose=verbose)
            except NotImplementedError:
                return cls._block(
                    ctx,
                    reason="No enforce_constraints for constrained action",
                    matched_gate="no_enforcement",
                )
            if pol.terminal:
                return pol.to_deterministic_result()
            ctx = pol.context

        domain_type = ACTION_DOMAINS.get(intent.action)
        domain_bundle = domain_bundle_for(domain_type) if domain_type else None
        if domain_bundle is not None:
            slice_ = deepcopy(
                (user_context.domain_constraints or {}).get(domain_type.value)
            )
            dr = domain_bundle.enforce(intent, slice_)
            if dr.terminal:
                merged = replace(dr, context=ctx)
                return merged.to_deterministic_result()

        struct = bundle.structural_gates(intent, ctx)
        if struct.terminal:
            return struct.to_deterministic_result()
        ctx = struct.context

        passive = cls._try_passive_read_allow(bundle, intent, action_permission, ctx)
        if passive is not None:
            return passive.to_deterministic_result()

        allow = bundle.allow_gates(intent, action_permission, ctx)
        if allow.terminal:
            return allow.to_deterministic_result()

        constraint_ctx = cls.build_constraint_prompt_context(
            bundle,
            action_permission,
            domain_bundle,
            domain_type,
            user_context,
        )
        ai_ctx = bundle.build_ai_context(intent, action_permission, ctx)
        ai_ctx = replace(ai_ctx, constraint_context=constraint_ctx)
        return cls._undecided(ctx, ai_context=ai_ctx)

    @staticmethod
    def build_constraint_prompt_context(
        bundle: ActionBundle,
        action_permission: ActionPermission,
        domain_bundle: DomainBundle | None,
        domain_type: Any | None,
        user_context: UserContext,
    ) -> ConstraintPromptContext:
        if action_permission.constraints is None:
            action_constraints = "No specific constraints"
        else:
            described = bundle.describe_constraints(action_permission)
            action_constraints = (
                described
                if described is not None
                else str(action_permission.constraints)
            )

        domain_lines: list[str] = []
        enforced: list[str] = []
        if domain_type is not None:
            domain_id = domain_type.value
            enforced.append(domain_id)
            slice_ = (user_context.domain_constraints or {}).get(domain_id)
            if domain_bundle is not None:
                described = domain_bundle.describe(slice_)
                domain_lines.append(
                    described if described is not None else f"{domain_id}: {slice_}"
                )
            elif slice_ is not None:
                domain_lines.append(f"{domain_id}: {slice_}")

        return ConstraintPromptContext(
            action_constraints=action_constraints,
            domain_constraints=domain_lines,
            enforced_domains=enforced,
        )

    @staticmethod
    def _try_passive_read_allow(
        bundle: ActionBundle,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
    ) -> BundlePhaseOutcome | None:
        action = intent.action.value
        if action not in bundle.passive_read_action_ids:
            return None
        if not action_permission.safe:
            return None
        return BundlePhaseOutcome.allow(
            ctx,
            reason=f"Permitted (deterministic: passive read): {action}",
            matched_gate="passive_read",
        )

    @staticmethod
    def _block(
        ctx: BundleContext,
        *,
        reason: str,
        matched_gate: str,
    ) -> BundleDeterministicResult:
        return BundlePhaseOutcome.block(
            ctx, reason=reason, matched_gate=matched_gate
        ).to_deterministic_result()

    @staticmethod
    def _undecided(
        ctx: BundleContext,
        *,
        ai_context: BundleAIContext,
    ) -> BundleDeterministicResult:
        return BundleDeterministicResult(
            decision="UNDECIDED",
            context=ctx,
            bundle_ai_context=ai_context,
        )
