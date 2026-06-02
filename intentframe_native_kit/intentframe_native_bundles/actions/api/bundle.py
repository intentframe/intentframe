"""HTTP API action bundle."""

from __future__ import annotations

import fnmatch

from intentframe_native_kit.action_registry.types import ActionType
from intentframe_bundle_sdk import IntentFrame

from intentframe_native_kit.intentframe_native_bundles.actions.api.constraints import ApiConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.api.onboarding_guardrails import api_onboarding_guardrails
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleContext,
    BundlePhaseOutcome,
)


class ApiActionBundle(ActionBundle):
    bundle_id = "api"
    action_ids = frozenset({
        ActionType.PAY_INVOICE.value,
        ActionType.HTTP_GET.value,
        ActionType.HTTP_POST.value,
        "HTTP_PUT",
        "HTTP_DELETE",
    })
    passive_read_action_ids = frozenset({ActionType.HTTP_GET.value})

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            ApiConstraints.model_validate(action_permission.constraints)

    async def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del verbose
        if action_permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = ApiConstraints.model_validate(action_permission.constraints)
        if constraints.max_amount is not None:
            amount = (intent.data or {}).get("amount")
            if amount is None:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        "Constraint violation: Amount is required to "
                        "evaluate max_amount policy"
                    ),
                    matched_gate="constraint",
                )
            try:
                if float(amount) > constraints.max_amount:
                    return BundlePhaseOutcome.block(
                        ctx,
                        reason=(
                            f"Constraint violation: Amount ${float(amount):,.2f} "
                            f"exceeds limit ${constraints.max_amount:,.2f}"
                        ),
                        matched_gate="constraint",
                    )
            except (TypeError, ValueError):
                return BundlePhaseOutcome.block(
                    ctx,
                    reason="Constraint violation: Invalid amount value",
                    matched_gate="constraint",
                )
        if constraints.allowed_endpoints is not None:
            endpoint = (intent.data or {}).get("url")
            if endpoint is None or (
                isinstance(endpoint, str) and not endpoint.strip()
            ):
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        "Constraint violation: URL is required to evaluate "
                        "allowed_endpoints policy"
                    ),
                    matched_gate="constraint",
                )
            for pattern in constraints.allowed_endpoints:
                if fnmatch.fnmatch(endpoint, pattern):
                    return BundlePhaseOutcome.continue_(ctx)
            return BundlePhaseOutcome.block(
                ctx,
                reason=f"Constraint violation: Endpoint '{endpoint}' not in allowed endpoints",
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    async def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = ApiConstraints.model_validate(action_permission.constraints)
        parts: list[str] = []
        if constraints.max_amount is not None:
            parts.append(f"Max amount: ${constraints.max_amount:,.2f}")
        if constraints.allowed_endpoints is not None:
            parts.append(f"Allowed endpoints: {', '.join(constraints.allowed_endpoints)}")
        return "; ".join(parts) if parts else "No specific constraints"

    def onboarding_guardrails(self) -> str:
        return api_onboarding_guardrails()
