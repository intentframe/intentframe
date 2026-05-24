"""Constraints for API category actions (PAY_INVOICE, HTTP_GET, etc.)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ApiConstraints(BaseModel):
    """Financial and endpoint constraints for API operations.

    Attributes:
        max_amount: Maximum monetary amount per action.
        allowed_endpoints: URL patterns for permitted API calls.
    """

    model_config = ConfigDict(frozen=True)

    max_amount: Optional[float] = None
    allowed_endpoints: Optional[list[str]] = None
