"""Constraints for EMAIL category actions (SEND_EMAIL, READ_EMAIL, etc.)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RecipientSource(BaseModel):
    """A dynamic source of allowed recipients.

    Sources are resolved by the Policy Registry at serve time into
    concrete email addresses, then merged with allowed_recipients.
    Guardian only ever sees the resolved flat list.

    Attributes:
        source: Source type — "contacts_all", "contacts_group".
        filter: Qualifier for the source (e.g. group name).
        enabled: Toggle without deleting.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    filter: str = ""
    enabled: bool = True


class EmailConstraints(BaseModel):
    """Recipient-based constraints for email operations.

    Attributes:
        allowed_recipients: Email address patterns for outbound emails.
            e.g. ["*@mycompany.com", "bob@partner.org"]
            Only relevant for SEND_EMAIL. Read/search are unconstrained.
        recipient_sources: Dynamic sources resolved at policy-serve time.
    """

    model_config = ConfigDict(frozen=True)

    allowed_recipients: list[str] = Field(default_factory=list)
    recipient_sources: list[RecipientSource] = Field(default_factory=list)
