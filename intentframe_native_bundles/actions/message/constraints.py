"""Constraints for MESSAGES category actions (SEND_MESSAGE)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContactSource(BaseModel):
    """A dynamic source of allowed contacts.

    Stored opaquely in the policy registry; resolved at runtime by
    ``MessageActionBundle.enforce_constraints`` into concrete contact
    identifiers, then merged with ``allowed_contacts``.

    Attributes:
        source: Source type — "contacts_all", "contacts_group".
        filter: Qualifier for the source (e.g. group name).
        enabled: Toggle without deleting.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    filter: str = ""
    enabled: bool = True


class MessageConstraints(BaseModel):
    """Contact-based constraints for messaging operations.

    Attributes:
        allowed_contacts: Contact identifiers (phone, email, name patterns).
        contact_sources: Dynamic sources resolved at runtime by the message bundle.
    """

    model_config = ConfigDict(frozen=True)

    allowed_contacts: list[str] = Field(default_factory=list)
    contact_sources: list[ContactSource] = Field(default_factory=list)
