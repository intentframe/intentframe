"""Typed intent data schema for the finance domain."""

from __future__ import annotations

from typing import Optional

from intentframe_core.domains.base import DomainSchema


class FinancialIntentData(DomainSchema):
    """Required fields for any financial action.

    When an action belongs to the finance domain (e.g. PAY_INVOICE),
    the Actor validates that ``IntentFrame.data`` conforms to this
    schema before entering the pipeline.
    """

    amount: float
    currency: str = "USD"
    recipient: Optional[str] = None
