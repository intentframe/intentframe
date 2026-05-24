"""Domain constraints for the finance domain (plugin-local schema)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class FinanceConstraints(BaseModel):
    """User-configured limits for the finance domain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_amount: Optional[float] = None
    allowed_currencies: Optional[list[str]] = None
    allowed_recipients: Optional[list[str]] = None
