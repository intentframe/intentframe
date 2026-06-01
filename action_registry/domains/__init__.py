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

from intentframe_core.domains.base import DomainSchema

from action_registry.domains.deletion import DeletionIntentData
from action_registry.domains.finance import FinancialIntentData
from action_registry.types import DomainType

DOMAIN_SCHEMAS: dict[DomainType, type[DomainSchema]] = {
    DomainType.FINANCE: FinancialIntentData,
    DomainType.DELETION: DeletionIntentData,
}

__all__ = [
    "DOMAIN_SCHEMAS",
    "DeletionIntentData",
    "FinancialIntentData",
]
