"""Constraint checker for API category actions."""

from __future__ import annotations

import fnmatch

from intentframe_core.types import IntentFrame
from intentframe_components.guardian.checkers.base import ConstraintChecker
from policy_registry.constraints.api import ApiConstraints


class ApiChecker(ConstraintChecker):
    """Financial and endpoint constraint enforcement for API operations."""

    def check(self, intent: IntentFrame, constraints: ApiConstraints) -> tuple[bool, str]:
        if constraints.max_amount is not None:
            amount = (intent.data or {}).get("amount")
            if amount is not None:
                try:
                    if float(amount) > constraints.max_amount:
                        return False, (
                            f"Amount ${float(amount):,.2f} exceeds "
                            f"limit ${constraints.max_amount:,.2f}"
                        )
                except (TypeError, ValueError):
                    return False, "Invalid amount value"

        if constraints.allowed_endpoints is not None:
            endpoint = intent.target or (intent.data or {}).get("url", "")
            for pattern in constraints.allowed_endpoints:
                if fnmatch.fnmatch(endpoint, pattern):
                    return True, ""
            return False, f"Endpoint '{endpoint}' not in allowed endpoints"

        return True, ""

    def summarize(self, constraints: ApiConstraints) -> str:
        parts: list[str] = []
        if constraints.max_amount is not None:
            parts.append(f"Max amount: ${constraints.max_amount:,.2f}")
        if constraints.allowed_endpoints is not None:
            parts.append(f"Allowed endpoints: {', '.join(constraints.allowed_endpoints)}")
        return "; ".join(parts) if parts else "No specific constraints"
