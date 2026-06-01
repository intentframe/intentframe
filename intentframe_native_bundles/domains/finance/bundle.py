"""Finance domain bundle — structural enforcement for financial intents."""

from __future__ import annotations

from action_registry.domains.finance import FinancialIntentData
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.domains.finance.constraints import FinanceConstraints
from intentframe_bundle_sdk.domain import DomainBundle
from intentframe_bundle_sdk.types import BundleContext, BundlePhaseOutcome


class FinanceDomainBundle(DomainBundle):
    bundle_id = "finance"
    domain_id = "finance"
    intent_schema = FinancialIntentData

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
            if amount is None:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        "Domain violation (finance): Amount is required to "
                        "evaluate max_amount policy"
                    ),
                    matched_gate="domain",
                )
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
            try:
                currency = FinancialIntentData.model_validate(data).currency
            except Exception:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        "Domain violation (finance): Invalid intent data for "
                        "currency policy evaluation"
                    ),
                    matched_gate="domain",
                )
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
            if recipient is None or (
                isinstance(recipient, str) and not recipient.strip()
            ):
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        "Domain violation (finance): Recipient is required to "
                        "evaluate allowed_recipients policy"
                    ),
                    matched_gate="domain",
                )
            if recipient not in constraints.allowed_recipients:
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
