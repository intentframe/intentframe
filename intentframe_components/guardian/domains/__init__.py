"""
Guardian domain modules — deterministic structural enforcement.

Domain modules are hard gates that run BEFORE AI evaluation.
They can BLOCK on structural violations but never ALLOW.
Passing a domain module means "structurally valid" — the intent
still goes through safety routing and AI for full semantic evaluation.
"""

from __future__ import annotations

from action_registry.types import DomainType
from intentframe_components.guardian.domains.base import DomainModule
from intentframe_components.guardian.domains.finance import FinanceModule
from intentframe_components.guardian.domains.deletion import DeletionModule

DOMAIN_MODULES: dict[DomainType, DomainModule] = {
    DomainType.FINANCE: FinanceModule(),
    DomainType.DELETION: DeletionModule(),
}

__all__ = [
    "DOMAIN_MODULES",
    "DeletionModule",
    "DomainModule",
    "FinanceModule",
]
