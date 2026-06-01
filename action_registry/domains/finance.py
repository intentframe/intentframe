"""Typed intent data schema for the finance domain."""

from __future__ import annotations

from typing import Optional

from intentframe_core.domains.base import DomainSchema


class FinancialIntentData(DomainSchema):
    """Finance-domain slice of ``IntentFrame.data``.

    Validates ``amount``, ``currency``, and ``recipient`` only. Other payload
    fields (e.g. deletion ``path``) are ignored so finance can compose with
    other routed domains on the same action.
    """

    amount: float
    currency: str = "USD"
    recipient: Optional[str] = None
