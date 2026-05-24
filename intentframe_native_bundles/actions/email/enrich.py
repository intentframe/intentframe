"""Email context enrichment — resolves message ids from local EDI database."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

logger = logging.getLogger(__name__)

EMAIL_MESSAGE_ACTIONS = frozenset({
    ActionType.GET_EMAIL.value,
    ActionType.REPLY_EMAIL.value,
    ActionType.FORWARD_EMAIL.value,
    ActionType.MARK_READ_EMAIL.value,
    ActionType.MOVE_EMAIL.value,
    ActionType.DELETE_EMAIL.value,
    ActionType.DOWNLOAD_ATTACHMENT.value,
})


class EmailLookupClient(Protocol):
    async def get_email(self, message_id: str, *, headers_only: bool = ...) -> Any: ...


async def _resolve_email_context(
    client: EmailLookupClient,
    message_id: str,
) -> dict[str, Any]:
    try:
        email = await client.get_email(message_id, headers_only=True)
        if email is None:
            return {}
        return {
            "email_subject": email.subject,
            "email_from": email.sender_raw or email.sender_email,
            "email_from_address": email.sender_email,
            "account_email": email.account_email,
            "mailbox": email.mailbox,
            "email_date": email.date,
            "has_attachments": email.has_attachments,
        }
    except Exception:
        logger.debug("email_context_enrichment_failed", exc_info=True)
        return {}


def _build_email_target(intent: IntentFrame, meta: dict[str, Any]) -> str:
    data = intent.data or {}
    action = intent.action.value
    message_id = data.get("rfc_message_id") or data.get("message_id", "")
    subject = meta.get("email_subject") or data.get("email_subject") or message_id
    sender = meta.get("email_from") or data.get("email_from") or "unknown"
    recipient = data.get("to", "")
    to_folder = data.get("to_folder", "")
    filename = data.get("filename", "")
    read = data.get("read", True)

    if action == ActionType.REPLY_EMAIL.value:
        return f'Reply to "{subject}" from {sender}'
    if action == ActionType.FORWARD_EMAIL.value:
        return f'Forward "{subject}" to {recipient}' if recipient else f'Forward "{subject}"'
    if action == ActionType.MARK_READ_EMAIL.value:
        label = "read" if read else "unread"
        return f'Mark {label}: "{subject}" from {sender}'
    if action == ActionType.MOVE_EMAIL.value:
        return f'Move "{subject}" to {to_folder}' if to_folder else f'Move "{subject}"'
    if action == ActionType.DELETE_EMAIL.value:
        return f'Email "{subject}" from {sender}'
    if action == ActionType.DOWNLOAD_ATTACHMENT.value:
        return f'Attachment {filename} on "{subject}"' if filename else f'Attachment on "{subject}"'
    if action == ActionType.GET_EMAIL.value:
        return f'Email "{subject}" from {sender}'
    return message_id


async def enrich_intent(intent: IntentFrame, *, client: EmailLookupClient) -> IntentFrame:
    if intent.action.value not in EMAIL_MESSAGE_ACTIONS:
        return intent

    data = dict(intent.data or {})
    message_id = str(data.get("rfc_message_id") or data.get("message_id", "")).strip()
    if not message_id:
        return intent

    meta = await _resolve_email_context(client, message_id)

    for key, value in meta.items():
        if not data.get(key):
            data[key] = value

    if intent.action.value == ActionType.REPLY_EMAIL.value and not data.get("to"):
        reply_to = meta.get("email_from_address") or ""
        if reply_to:
            data["to"] = reply_to

    target = intent.target
    if not target or target == message_id:
        target = _build_email_target(intent, meta)

    return intent.model_copy(update={"target": target, "data": data})
