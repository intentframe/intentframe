"""Finance domain module — deterministic structural enforcement."""

from __future__ import annotations

from action_registry.types import DomainType
from intentframe_core.types import IntentFrame
from policy_registry.domains.base import DomainConstraints
from policy_registry.domains.finance import FinanceConstraints
from intentframe_components.guardian.domains.base import DomainModule


class FinanceModule(DomainModule):
    """Structural enforcer for the finance domain.

    Checks that can BLOCK (deterministic, before AI):
    - amount > max_amount
    - currency not in allowed_currencies
    - recipient not in allowed_recipients

    What this module CANNOT catch (AI handles after module passes):
    - Scope mismatch (agent paying for something outside its mandate)
    - Phishing / spoofed vendor invoices
    - Aggregate spending across multiple transactions
    - Hallucinated invoices
    """

    @property
    def domain(self) -> DomainType:
        return DomainType.FINANCE

    def check(
        self,
        intent: IntentFrame,
        constraints: DomainConstraints,
    ) -> tuple[bool, str]:
        if not isinstance(constraints, FinanceConstraints):
            return True, ""

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
