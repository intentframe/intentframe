"""Domain -> IMAP/SMTP host mapping for well-known email providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    imap_host: str
    smtp_host: str
    imap_port: int = 993
    smtp_port: int = 465


KNOWN_PROVIDERS: dict[str, ProviderInfo] = {
    "gmail.com": ProviderInfo(
        name="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
    ),
    "googlemail.com": ProviderInfo(
        name="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
    ),
    "outlook.com": ProviderInfo(
        name="outlook",
        imap_host="outlook.office365.com",
        smtp_host="smtp.office365.com",
        smtp_port=587,
    ),
    "hotmail.com": ProviderInfo(
        name="outlook",
        imap_host="outlook.office365.com",
        smtp_host="smtp.office365.com",
        smtp_port=587,
    ),
    "live.com": ProviderInfo(
        name="outlook",
        imap_host="outlook.office365.com",
        smtp_host="smtp.office365.com",
        smtp_port=587,
    ),
    "yahoo.com": ProviderInfo(
        name="yahoo",
        imap_host="imap.mail.yahoo.com",
        smtp_host="smtp.mail.yahoo.com",
    ),
    "icloud.com": ProviderInfo(
        name="icloud",
        imap_host="imap.mail.me.com",
        smtp_host="smtp.mail.me.com",
        smtp_port=587,
    ),
    "me.com": ProviderInfo(
        name="icloud",
        imap_host="imap.mail.me.com",
        smtp_host="smtp.mail.me.com",
        smtp_port=587,
    ),
    "mac.com": ProviderInfo(
        name="icloud",
        imap_host="imap.mail.me.com",
        smtp_host="smtp.mail.me.com",
        smtp_port=587,
    ),
}


def resolve_provider(email_address: str) -> ProviderInfo:
    """Resolve IMAP/SMTP settings from an email address domain.

    Falls back to ``imap.<domain>`` / ``smtp.<domain>`` for unknown providers.
    """
    domain = email_address.rsplit("@", 1)[-1].lower()
    if domain in KNOWN_PROVIDERS:
        return KNOWN_PROVIDERS[domain]
    return ProviderInfo(
        name="other",
        imap_host=f"imap.{domain}",
        smtp_host=f"smtp.{domain}",
    )
