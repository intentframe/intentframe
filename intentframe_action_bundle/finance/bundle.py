"""Finance action and domain bundles."""

from __future__ import annotations

import fnmatch

from action_registry.types import ActionType, DomainType
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.api.constraints import ApiConstraints
from intentframe_action_bundle.finance.constraints import FinanceConstraints
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.domain import DomainBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleContext,
    BundlePhaseOutcome,
)


class FinanceActionBundle(ActionBundle):
    bundle_id = "finance"
    action_ids = frozenset({ActionType.PAY_INVOICE.value})

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            ApiConstraints.model_validate(action_permission.constraints)

    def enforce_constraints(
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
            if amount is not None:
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
            endpoint = intent.target or (intent.data or {}).get("url", "")
            for pattern in constraints.allowed_endpoints:
                if fnmatch.fnmatch(endpoint, pattern):
                    return BundlePhaseOutcome.continue_(ctx)
            return BundlePhaseOutcome.block(
                ctx,
                reason=f"Constraint violation: Endpoint '{endpoint}' not in allowed endpoints",
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = ApiConstraints.model_validate(action_permission.constraints)
        parts: list[str] = []
        if constraints.max_amount is not None:
            parts.append(f"Max amount: ${constraints.max_amount:,.2f}")
        if constraints.allowed_endpoints is not None:
            parts.append(f"Allowed endpoints: {', '.join(constraints.allowed_endpoints)}")
        return "; ".join(parts) if parts else "No specific constraints"


class FinanceDomainBundle(DomainBundle):
    bundle_id = "finance"
    domain_type = DomainType.FINANCE

    def validate(self, domain_constraints: dict | None) -> None:
        if domain_constraints is not None:
            FinanceConstraints.model_validate(domain_constraints)

    def enforce(
        self,
        intent: IntentFrame,
        domain_constraints: dict | None,
    ) -> BundlePhaseOutcome:
        ctx = BundleContext(intent=intent.model_copy(deep=True))
        if domain_constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = FinanceConstraints.model_validate(domain_constraints)
        data = intent.data or {}

        if constraints.max_amount is not None:
            amount = data.get("amount")
            if amount is not None:
                try:
                    if float(amount) > constraints.max_amount:
                        return BundlePhaseOutcome.block(
                            ctx,
                            reason=(
                                f"Domain violation (finance): Amount "
                                f"${float(amount):,.2f} exceeds domain limit "
                                f"${constraints.max_amount:,.2f}"
                            ),
                            matched_gate="domain",
                        )
                except (TypeError, ValueError):
                    return BundlePhaseOutcome.block(
                        ctx,
                        reason="Domain violation (finance): Invalid amount value",
                        matched_gate="domain",
                    )

        if constraints.allowed_currencies is not None:
            currency = data.get("currency", "USD")
            if currency not in constraints.allowed_currencies:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        f"Domain violation (finance): Currency '{currency}' "
                        f"not in allowed currencies: {constraints.allowed_currencies}"
                    ),
                    matched_gate="domain",
                )

        if constraints.allowed_recipients is not None:
            recipient = data.get("recipient")
            if recipient is not None and recipient not in constraints.allowed_recipients:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        f"Domain violation (finance): Recipient '{recipient}' "
                        "not in allowed recipients"
                    ),
                    matched_gate="domain",
                )

        return BundlePhaseOutcome.continue_(ctx)

    def describe(self, domain_constraints: dict | None) -> str | None:
        if domain_constraints is None:
            return None
        constraints = FinanceConstraints.model_validate(domain_constraints)
        parts: list[str] = []
        if constraints.max_amount is not None:
            parts.append(f"max_amount=${constraints.max_amount:,.2f}")
        if constraints.allowed_currencies is not None:
            parts.append(f"currencies={constraints.allowed_currencies}")
        if constraints.allowed_recipients is not None:
            parts.append(f"recipients={constraints.allowed_recipients}")
        return "; ".join(parts) if parts else "finance domain constraints configured"
