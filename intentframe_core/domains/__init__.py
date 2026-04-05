"""
Typed intent data schemas for critical domains.

These are protocol contracts: they define what goes inside
``IntentFrame.data`` when the action belongs to a critical domain.

Both the Actor (producer) and Guardian (consumer) import from here.
Schemas are validated at the Actor boundary — if a critical-domain
action arrives with malformed data, it is rejected before entering
the pipeline.
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
