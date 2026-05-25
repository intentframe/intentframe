"""Dynamic source rules resolved by the policy registry at serve time."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RecipientSource(BaseModel):
    """A dynamic source of allowed email recipients."""

    model_config = ConfigDict(frozen=True)

    source: str
    filter: str = ""
    enabled: bool = True


class ContactSource(BaseModel):
    """A dynamic source of allowed message contacts."""

    model_config = ConfigDict(frozen=True)

    source: str
    filter: str = ""
    enabled: bool = True
