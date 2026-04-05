"""Pydantic models for the email sync service."""

from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AccountNotFoundError(Exception):
    """Raised when an operation targets an account not in config."""

    def __init__(self, account_email: str, configured: list[str] | None = None) -> None:
        self.account_email = account_email
        self.configured = configured or []
        available = f" Available: {configured}" if configured else ""
        super().__init__(f"Account {account_email!r} not configured.{available}")


class Account(BaseModel):
    email: str
    display_name: str = ""
    provider: str = "other"
    imap_host: str = ""
    smtp_host: str = ""
    imap_port: int = 993
    smtp_port: int = 465
    status: str = "active"
    last_error: Optional[str] = None
    created_at: str = ""


class Folder(BaseModel):
    name: str
    role: Optional[str] = None
    delimiter: str = "/"
    flags: list[str] = Field(default_factory=list)
    message_count: int = 0
    unseen_count: int = 0


class Email(BaseModel):
    id: int = 0
    uid: int = 0
    message_id: str = ""
    account_email: str = ""
    mailbox: str = ""
    subject: str = ""
    sender_raw: str = ""
    sender_name: str = ""
    sender_email: str = ""
    sender_domain: str = ""
    to_recipients: list[dict] = Field(default_factory=list)
    cc_recipients: list[dict] = Field(default_factory=list)
    date: str = ""
    body_plain: str = ""
    body_html: str = ""
    flags: list[str] = Field(default_factory=list)
    size_bytes: int = 0
    has_attachments: bool = False
    in_reply_to: str = ""
    references_hdr: str = ""
    headers_raw: str = ""
    content_level: int = 0
    synced_at: str = ""


class Attachment(BaseModel):
    id: int = 0
    email_id: int = 0
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    content_id: str = ""
    is_inline: bool = False
    storage_path: Optional[str] = None


class Event(BaseModel):
    id: int = 0
    event_type: str = ""
    account_email: str = ""
    message_id: str = ""
    data: dict = Field(default_factory=dict)
    created_at: str = ""


class SendResult(BaseModel):
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class DraftResult(BaseModel):
    success: bool
    uid: Optional[int] = None
    error: Optional[str] = None
