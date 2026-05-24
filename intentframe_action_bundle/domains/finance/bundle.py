"""Finance domain bundle — structural enforcement for financial intents."""

from __future__ import annotations

from typing import Any

from intentframe_core.types import IntentFrame
from intentframe_bundle_sdk.domain import DomainBundle
from intentframe_bundle_sdk.types import BundleContext
from policy_registry.domains.finance import FinanceConstraints
from policy_registry.domains.base import DomainConstraints


class FinanceDomainBundle(DomainBundle):
    domain_id = "finance"

    def validate_constraints(self, constraints: dict[str, Any]) -> None:
        FinanceConstraints.model_validate(constraints)

    def check_domain(
        self,
        intent: IntentFrame,
        constraints: Any | None,
        ctx: BundleContext,
    ) -> tuple[bool, str]:
        del ctx
        if constraints is None:
            return True, ""
        if isinstance(constraints, DomainConstraints) and not isinstance(
            constraints, FinanceConstraints
        ):
            return True, ""
        if not isinstance(constraints, FinanceConstraints):
            constraints = FinanceConstraints.model_validate(constraints)

        data = intent.data or {}

        if constraints.max_amount is not None:
            amount = data.get("amount")
            if amount is not None:
                try:
                    if float(amount) > constraints.max_amount:
                        return False, (
                            f"Amount ${float(amount):,.2f} exceeds domain "
                            f"limit ${constraints.max_amount:,.2f}"
                        )
                except (TypeError, ValueError):
                    return False, "Invalid amount value in financial intent"

        if constraints.allowed_currencies is not None:
            currency = data.get("currency", "USD")
            if currency not in constraints.allowed_currencies:
                return False, (
                    f"Currency '{currency}' not in allowed currencies: "
                    f"{constraints.allowed_currencies}"
                )

        if constraints.allowed_recipients is not None:
            recipient = data.get("recipient")
            if recipient is not None and recipient not in constraints.allowed_recipients:
                return False, (
                    f"Recipient '{recipient}' not in allowed recipients"
                )

        return True, ""

    def summarize_constraints(self, constraints: Any) -> str:
        if not isinstance(constraints, FinanceConstraints):
            constraints = FinanceConstraints.model_validate(constraints)
        parts: list[str] = []
        if constraints.max_amount is not None:
            parts.append(f"max_amount=${constraints.max_amount:,.2f}")
        if constraints.allowed_currencies is not None:
            parts.append(f"currencies={constraints.allowed_currencies}")
        if constraints.allowed_recipients is not None:
            parts.append(f"recipients={constraints.allowed_recipients}")
        return "; ".join(parts) if parts else "finance domain constraints configured"
