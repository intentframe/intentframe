"""
Typed intent data schemas for critical domains.

Each schema is a **slice** of ``IntentFrame.data`` for one domain's risk
surface. Schemas ignore unrelated fields (``extra="ignore"``), so an action
routed to multiple domains can carry a combined payload and each domain
validates only its own fields.

The Actor validates the slice for the action's primary domain (see
``ACTION_DOMAINS``). The Bundle SDK runner validates every routed domain slice
before ``DomainBundle.enforce()``.
"""

from __future__ import annotations

from action_registry.types import DomainType
from intentframe_core.domains.base import DomainSchema
from intentframe_core.domains.finance import FinancialIntentData
from intentframe_core.domains.deletion import DeletionIntentData

DOMAIN_SCHEMAS: dict[DomainType, type[DomainSchema]] = {
    DomainType.FINANCE: FinancialIntentData,
    DomainType.DELETION: DeletionIntentData,
}

__all__ = [
    "DOMAIN_SCHEMAS",
    "DeletionIntentData",
    "DomainSchema",
    "FinancialIntentData",
]
