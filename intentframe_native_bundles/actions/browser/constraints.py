"""Constraints for BROWSER category actions (OPEN_URL, SEARCH_WEB, etc.)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BrowserConstraints(BaseModel):
    """URL-based constraints for browser operations.

    Attributes:
        allowed_urls: URL patterns for permitted navigation.
            e.g. ["https://docs.google.com/*", "https://github.com/*"]
    """

    model_config = ConfigDict(frozen=True)

    allowed_urls: list[str] = Field(min_length=1)
