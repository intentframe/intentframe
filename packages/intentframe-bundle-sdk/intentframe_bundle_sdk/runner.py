"""Host-only deterministic orchestration — fixed gate order (authors do not override).

The runner is the sole runtime caller of bundle and domain hooks. Constraint
prompt text is built here on the UNDECIDED path only; terminal ALLOW/BLOCK
results carry no ``constraint_context``.

Per-hook deadlines
------------------
Every async hook is wrapped with ``asyncio.wait_for`` using a configurable
timeout.  Timeouts surface as a fail-closed BLOCK with matched_gate set to
``"hook_timeout"`` or ``"hook_crash"`` rather than propagating uncaught
exceptions into the pipeline.

Default per-hook budgets (seconds):

    prepare_evidence    5.0
    enrich              5.0
    enforce_constraints 5.0   — most likely to call external services
    structural_gates    2.0
    allow_gates         2.0
    build_ai_context    5.0
    describe_constraints 2.0

These can be overridden by passing a ``HookTimeouts`` instance to
``run_action_bundle``.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from intentframe_bundle_sdk.constraints import describe_permission_constraints
from intentframe_bundle_sdk.domain import check_domain_intent_shape
from intentframe_bundle_sdk.registry import domain_bundle_for, domains_for_action
from intentframe_bundle_sdk.trace import emit_skip, make_trace_id, traced_acall, traced_call
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleAIContext,
    BundleContext,
    BundleDeterministicResult,
    BundleHookCrashed,
    BundleHookTimeout,
    BundlePhaseOutcome,
    ConstraintPromptContext,
    action_permission_from_policy,
    record_enrichment,
)

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame, UserContext

    from intentframe_bundle_sdk.action import ActionBundle
    from intentframe_bundle_sdk.domain import DomainBundle


@dataclass(frozen=True)
class HookTimeouts:
    """Per-hook timeout budgets in seconds."""

    prepare_evidence: float = 5.0
    enrich: float = 5.0
    enforce_constraints: float = 5.0
    structural_gates: float = 2.0
    allow_gates: float = 2.0
    build_ai_context: float = 5.0
    describe_constraints: float = 2.0


_DEFAULT_TIMEOUTS = HookTimeouts()


async def _call_hook(
    hook_fn: Any,
    /,
    *args: Any,
    bundle_id: str,
    hook: str,
    timeout_s: float,
    trace_id: str = "",
    **kwargs: Any,
) -> Any:
    """Await ``hook_fn(*args, **kwargs)`` with a deadline; emit a trace record.

    Converts ``asyncio.TimeoutError`` → :class:`BundleHookTimeout` and any
    other exception → :class:`BundleHookCrashed`.  ``NotImplementedError`` is
    re-raised as-is so callers can handle the "not implemented" contract.

    The full input dump (all named args) and the return value are written to
    ``bundle-sdk.log`` via :mod:`intentframe_bundle_sdk.trace` before any
    exception conversion, so every hook invocation leaves a forensic record
    regardless of outcome.
    """
    try:
        return await traced_acall(
            hook_fn,
            *args,
            lane="runtime",
            trace_id=trace_id,
            phase=hook,
            timeout_s=timeout_s,
            terminal_from=lambda r: getattr(r, "terminal", False),
            **kwargs,
        )
    except asyncio.TimeoutError as exc:
        raise BundleHookTimeout(bundle_id, hook, timeout_s) from exc
    except (BundleHookTimeout, BundleHookCrashed):
        raise
    except NotImplementedError:
        raise
    except Exception as exc:
        raise BundleHookCrashed(bundle_id, hook, exc) from exc


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
        timeouts: HookTimeouts = _DEFAULT_TIMEOUTS,
    ) -> BundleDeterministicResult:
        action_permission = action_permission_from_policy(permission)
        ctx = BundleContext(intent=intent.model_copy(deep=True))
        trace_id = make_trace_id(intent, bundle.bundle_id)

        # ── prepare_evidence ───────────────────────────────────────────
        try:
            prep = await _call_hook(
                bundle.prepare_evidence, intent, ctx,
                bundle_id=bundle.bundle_id,
                hook="prepare_evidence",
                timeout_s=timeouts.prepare_evidence,
                trace_id=trace_id,
                verbose=verbose,
            )
        except (BundleHookTimeout, BundleHookCrashed) as exc:
            return cls._block_from_hook_error(ctx, exc)
        if prep.terminal:
            return prep.to_deterministic_result()
        ctx = prep.context

        # ── enrich ─────────────────────────────────────────────────────
        try:
            enriched = await _call_hook(
                bundle.enrich, intent, action_permission, ctx,
                bundle_id=bundle.bundle_id,
                hook="enrich",
                timeout_s=timeouts.enrich,
                trace_id=trace_id,
                verbose=verbose,
            )
        except (BundleHookTimeout, BundleHookCrashed) as exc:
            return cls._block_from_hook_error(ctx, exc)
        if enriched.terminal:
            raise RuntimeError(
                f"bundle {bundle.bundle_id!r} enrich() returned terminal "
                f"{enriched.decision.value} — enrichment must not BLOCK or ALLOW"
            )
        ctx = enriched.context
        record_enrichment(ctx, bundle_id=bundle.bundle_id)

        # ── enforce_constraints ────────────────────────────────────────
        if action_permission.constraints is not None:
            frozen = action_permission.copy_with_constraints(
                deepcopy(action_permission.constraints)
            )
            try:
                pol = await _call_hook(
                    bundle.enforce_constraints, intent, frozen, ctx,
                    bundle_id=bundle.bundle_id,
                    hook="enforce_constraints",
                    timeout_s=timeouts.enforce_constraints,
                    trace_id=trace_id,
                    verbose=verbose,
                )
            except NotImplementedError:
                return cls._block(
                    ctx,
                    reason="No enforce_constraints for constrained action",
                    matched_gate="no_enforcement",
                )
            except (BundleHookTimeout, BundleHookCrashed) as exc:
                return cls._block_from_hook_error(ctx, exc)
            if pol.terminal:
                return pol.to_deterministic_result()
            ctx = pol.context
        else:
            emit_skip(
                lane="runtime",
                trace_id=trace_id,
                phase="enforce_constraints",
                reason="action_permission.constraints is None",
            )

        # ── domain enforce ─────────────────────────────────────────────
        action_id = intent.action
        domain_ids = domains_for_action(action_id)
        for domain_id in domain_ids:
            domain_bundle = domain_bundle_for(domain_id)
            if domain_bundle is None:
                emit_skip(
                    lane="runtime",
                    trace_id=trace_id,
                    phase=f"domain_enforce:{domain_id}",
                    reason="no domain bundle registered",
                )
                continue
            shape = traced_call(
                check_domain_intent_shape, domain_bundle, intent,
                lane="runtime",
                trace_id=trace_id,
                phase=f"domain_schema:{domain_id}",
                terminal_from=lambda r: r.terminal,
            )
            if shape.terminal:
                merged = replace(shape, context=ctx)
                return merged.to_deterministic_result()
            slice_ = deepcopy(
                (user_context.domain_constraints or {}).get(domain_id)
            )
            dr = traced_call(
                domain_bundle.enforce, intent, slice_,
                lane="runtime",
                trace_id=trace_id,
                phase=f"domain_enforce:{domain_id}",
                terminal_from=lambda r: r.terminal,
            )
            if dr.terminal:
                merged = replace(dr, context=ctx)
                return merged.to_deterministic_result()

        # ── structural_gates ───────────────────────────────────────────
        try:
            struct = await _call_hook(
                bundle.structural_gates, intent, ctx,
                bundle_id=bundle.bundle_id,
                hook="structural_gates",
                timeout_s=timeouts.structural_gates,
                trace_id=trace_id,
            )
        except (BundleHookTimeout, BundleHookCrashed) as exc:
            return cls._block_from_hook_error(ctx, exc)
        if struct.terminal:
            return struct.to_deterministic_result()
        ctx = struct.context

        # ── passive_read ALLOW ─────────────────────────────────────────
        passive = traced_call(
            cls._try_passive_read_allow, bundle, intent, action_permission, ctx,
            lane="runtime",
            trace_id=trace_id,
            phase="_try_passive_read_allow",
            terminal_from=lambda r: r is not None,
        )
        if passive is not None:
            return passive.to_deterministic_result()

        # ── allow_gates ────────────────────────────────────────────────
        try:
            allow = await _call_hook(
                bundle.allow_gates, intent, action_permission, ctx,
                bundle_id=bundle.bundle_id,
                hook="allow_gates",
                timeout_s=timeouts.allow_gates,
                trace_id=trace_id,
            )
        except (BundleHookTimeout, BundleHookCrashed) as exc:
            return cls._block_from_hook_error(ctx, exc)
        if allow.terminal:
            return allow.to_deterministic_result()

        # ── UNDECIDED — build AI context ───────────────────────────────
        constraint_ctx = await cls.build_constraint_prompt_context(
            bundle,
            action_permission,
            domain_ids,
            user_context,
            timeout_s=timeouts.describe_constraints,
            trace_id=trace_id,
        )
        try:
            ai_ctx = await _call_hook(
                bundle.build_ai_context, intent, action_permission, ctx,
                bundle_id=bundle.bundle_id,
                hook="build_ai_context",
                timeout_s=timeouts.build_ai_context,
                trace_id=trace_id,
            )
        except (BundleHookTimeout, BundleHookCrashed):
            ai_ctx = BundleAIContext()
        ai_ctx = replace(ai_ctx, constraint_context=constraint_ctx)
        return cls._undecided(ctx, ai_context=ai_ctx)

    @staticmethod
    async def build_constraint_prompt_context(
        bundle: ActionBundle,
        action_permission: ActionPermission,
        domain_ids: tuple[str, ...],
        user_context: UserContext,
        *,
        timeout_s: float = _DEFAULT_TIMEOUTS.describe_constraints,
        trace_id: str = "",
    ) -> ConstraintPromptContext:
        try:
            action_constraints = await _call_hook(
                describe_permission_constraints, bundle, action_permission,
                bundle_id=bundle.bundle_id,
                hook="describe_constraints",
                timeout_s=timeout_s,
                trace_id=trace_id,
            )
        except (BundleHookTimeout, BundleHookCrashed):
            action_constraints = str(action_permission.constraints or "No specific constraints")

        domain_lines: list[str] = []
        enforced: list[str] = []
        for domain_id in domain_ids:
            enforced.append(domain_id)
            slice_ = (user_context.domain_constraints or {}).get(domain_id)
            domain_bundle = domain_bundle_for(domain_id)
            if domain_bundle is not None:
                described = traced_call(
                    domain_bundle.describe, slice_,
                    lane="runtime",
                    trace_id=trace_id,
                    phase=f"domain_describe:{domain_id}",
                )
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
        action = intent.action
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
        dg_exception: str = "",
    ) -> BundleDeterministicResult:
        result = BundlePhaseOutcome.block(
            ctx, reason=reason, matched_gate=matched_gate
        ).to_deterministic_result()
        if dg_exception:
            return replace(result, dg_exception=dg_exception)
        return result

    @staticmethod
    def _block_from_hook_error(
        ctx: BundleContext,
        exc: BundleHookTimeout | BundleHookCrashed,
    ) -> BundleDeterministicResult:
        dg_exception = repr(exc.cause) if isinstance(exc, BundleHookCrashed) else ""
        return DeterministicRunner._block(
            ctx,
            reason=str(exc),
            matched_gate=_gate_for(exc),
            dg_exception=dg_exception,
        )

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


def _gate_for(exc: BundleHookTimeout | BundleHookCrashed) -> str:
    if isinstance(exc, BundleHookTimeout):
        return "hook_timeout"
    return "hook_crash"
