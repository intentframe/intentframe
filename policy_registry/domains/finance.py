"""Domain constraints for the finance domain."""

from __future__ import annotations

from typing import Literal, Optional

from action_registry.types import DomainType
from policy_registry.domains.base import DomainConstraints


class FinanceConstraints(DomainConstraints):
    """User-configured limits for the finance domain.

    Enforced deterministically by the finance Guardian module.
    Passing these checks does NOT mean the action is safe —
    AI still evaluates for scope, phishing, hallucination, etc.
    """

    domain: Literal[DomainType.FINANCE] = DomainType.FINANCE
    max_amount: Optional[float] = None
    allowed_currencies: Optional[list[str]] = None
    allowed_recipients: Optional[list[str]] = None
