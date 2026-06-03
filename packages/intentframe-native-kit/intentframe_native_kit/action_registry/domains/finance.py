"""Finance-domain intent slice for ``IntentFrame.data``.

Validates ``amount``, ``currency``, and ``recipient`` — the fields finance
domain policy and ``PAY_INVOICE`` enforcement care about. Other payload keys
(e.g. deletion ``path``) are ignored so finance can compose with other routed
domains on the same action.

Used by ``FinanceDomainBundle`` and optionally by agent authors via
``DOMAIN_SCHEMAS`` for local pre-flight validation.
"""

from __future__ import annotations

from typing import Optional

from intentframe_bundle_sdk import DomainSchema


class FinancialIntentData(DomainSchema):
    """Finance-domain slice of ``IntentFrame.data``.

    Validates ``amount``, ``currency``, and ``recipient`` only. Other payload
    fields (e.g. deletion ``path``) are ignored so finance can compose with
    other routed domains on the same action.
    """

    amount: float
    currency: str = "USD"
    recipient: Optional[str] = None
