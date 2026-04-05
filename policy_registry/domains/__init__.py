"""
Domain-level constraints — user-configured limits for critical domains.

These sit alongside per-category constraints (FileConstraints, etc.)
but operate at the domain level rather than per-action-type.  Domain
constraints are consumed by Guardian domain modules for deterministic
structural enforcement.
"""

from __future__ import annotations

from action_registry.types import DomainType
from policy_registry.domains.base import DomainConstraints
from policy_registry.domains.finance import FinanceConstraints
from policy_registry.domains.deletion import DeletionConstraints

DOMAIN_CONSTRAINT_TYPES: dict[DomainType, type[DomainConstraints]] = {
    DomainType.FINANCE: FinanceConstraints,
    DomainType.DELETION: DeletionConstraints,
}

__all__ = [
    "DOMAIN_CONSTRAINT_TYPES",
    "DeletionConstraints",
    "DomainConstraints",
    "FinanceConstraints",
]
