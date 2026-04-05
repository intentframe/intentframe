"""Email context enrichment — runtime-side pre-analysis step.

For message-based email actions (reply, forward, delete, move, etc.)
the agent only sends an opaque ``rfc_message_id``.  This enricher resolves
the email's headers from the local EDI SQLite database and populates
``IntentFrame.target`` and ``IntentFrame.data`` so Analysis Engine and
Guardian can reason about the actual message, not just an ID.

Runs in ``IntentFrameRuntime._process_intent_impl`` after command_shield
and before the Analysis Engine — same pattern as all deterministic
pre-pipeline gates.

TRUST LEVEL: ``target`` and ``data`` remain in the UNTRUSTED prompt
boundary even after enrichment.  The lookup method is deterministic
(local SQLite), but the *content* — subject lines, sender names,
mailbox labels — originates from external email accounts and is
attacker-controlled.  A malicious email can embed prompt-injection
text in its subject or sender field.  Treating this data as trusted
would allow a crafted email to influence AE/Guardian decisions.

``observed_context`` (the planned trusted field) is NOT appropriate
for email metadata.  It is only safe for data with no external attack
surface, such as local filesystem stat() results where the user is the
only author.
"""

from __future__ import annotations

import logging
from typing import Any

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

logger = logging.getLogger(__name__)

_EMAIL_MESSAGE_ACTIONS = frozenset({
    ActionType.GET_EMAIL.value,
    ActionType.REPLY_EMAIL.value,
    ActionType.FORWARD_EMAIL.value,
    ActionType.MARK_READ_EMAIL.value,
    ActionType.MOVE_EMAIL.value,
    ActionType.DELETE_EMAIL.value,
    ActionType.DOWNLOAD_ATTACHMENT.value,
})

_email_client: Any | None = None


async def _get_email_client() -> Any:
    global _email_client
    if _email_client is None:
        from external_data_ingestion.email.client import EmailClient

        _email_client = await EmailClient.create()
    return _email_client


async def _resolve_email_context(message_id: str) -> dict[str, Any]:
    """Look up email headers from the local EDI database."""
    try:
        client = await _get_email_client()
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
    """Build a human-readable target string from resolved metadata."""
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


async def enrich_intent(intent: IntentFrame) -> IntentFrame:
    """Enrich a message-based email IntentFrame with resolved metadata.

    Returns the original intent unchanged for non-email actions or when
    the enrichment has nothing to add (graceful degradation).
    """
    if intent.action.value not in _EMAIL_MESSAGE_ACTIONS:
        return intent

    data = dict(intent.data or {})
    message_id = str(data.get("rfc_message_id") or data.get("message_id", "")).strip()
    if not message_id:
        return intent

    meta = await _resolve_email_context(message_id)

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


async def close() -> None:
    """Release the module-level email client connection."""
    global _email_client
    if _email_client is not None:
        await _email_client.close()
        _email_client = None
