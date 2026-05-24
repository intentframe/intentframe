"""
Domain-level constraint schemas — Pydantic models for bundle validation.

Policy storage uses opaque dicts; bundles validate via these schemas at runtime.
"""

from __future__ import annotations

from policy_registry.domains.base import DomainConstraints
from policy_registry.domains.deletion import DeletionConstraints
from policy_registry.domains.finance import FinanceConstraints

__all__ = [
    "DeletionConstraints",
    "DomainConstraints",
    "FinanceConstraints",
]
