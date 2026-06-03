"""Constraints for CALENDAR category actions (CREATE_EVENT, LIST_EVENTS)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class CalendarConstraints(BaseModel):
    """Constraints for calendar operations.

    Attributes:
        allowed_calendars: Calendar names the user permits.
            None means all calendars are accessible.
    """

    model_config = ConfigDict(frozen=True)

    allowed_calendars: Optional[list[str]] = None
