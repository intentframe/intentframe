"""
Mail adapter -- delegates to EDI (External Data Ingestion) email service.

EDI provides a background sync daemon with IMAP IDLE, a local SQLite cache
with FTS5 search, and credential management via the intentframe vault.
The adapter validates that the requested account is both configured and
actively synced before dispatching to EmailClient.

Actions that operate on an account (SEND, READ, SEARCH) require
``account_email`` in params.  Actions that operate on a specific message
(GET, REPLY, FORWARD, MARK_READ, MOVE, DELETE, DOWNLOAD_ATTACHMENT)
require ``message_id`` — the account is resolved internally from the DB.

**Account discovery (executor only):** If SEND/READ/SEARCH is executed
without ``account_email``, the adapter does not pick a default; it returns
``ExecutionResult(success=False, ...)`` whose error text lists addresses
from ``EmailClient.get_active_accounts()``. That is *not* a dedicated
LIST_EMAIL_ACCOUNTS action and does not appear in the action registry.
Jarvis tools still declare ``account_email`` as required on the LLM tool
schema, so callers typically cannot rely on this path without omitting the
field at the action payload layer. See ``jarvis_pa/README.md`` (Email and
account discovery) and ``jarvis/skills/apple-mail/SKILL.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from intentframe_native_kit.action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)

_MISSING_EDI_ERROR = (
    "EDI email client is not installed. Install the product-side "
    "external_data_ingestion package in this runtime to use native-kit email actions."
)

_ACCOUNT_ACTIONS = frozenset({
    ActionType.SEND_EMAIL.value,
    ActionType.READ_EMAIL.value,
    ActionType.SEARCH_EMAIL.value,
})

_MESSAGE_ACTIONS = frozenset({
    ActionType.GET_EMAIL.value,
    ActionType.REPLY_EMAIL.value,
    ActionType.FORWARD_EMAIL.value,
    ActionType.MARK_READ_EMAIL.value,
    ActionType.MOVE_EMAIL.value,
    ActionType.DELETE_EMAIL.value,
    ActionType.DOWNLOAD_ATTACHMENT.value,
})


class MailAdapter(CapabilityAdapter):
    """Email adapter backed by the EDI email sync service."""

    def __init__(self, **_kwargs) -> None:
        self._client = None

    def supported_actions(self) -> list[str]:
        return [
            ActionType.SEND_EMAIL.value,
            ActionType.READ_EMAIL.value,
            ActionType.SEARCH_EMAIL.value,
            ActionType.GET_EMAIL.value,
            ActionType.REPLY_EMAIL.value,
            ActionType.FORWARD_EMAIL.value,
            ActionType.MARK_READ_EMAIL.value,
            ActionType.MOVE_EMAIL.value,
            ActionType.DELETE_EMAIL.value,
            ActionType.DOWNLOAD_ATTACHMENT.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="mail",
            name="Mail Adapter",
            description="Email via EDI email sync service",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def _get_client(self):
        """Lazy-init the EDI EmailClient (requires vault + config)."""
        if self._client is None:
            try:
                from external_data_ingestion.email.client import EmailClient
            except ModuleNotFoundError as exc:
                if exc.name == "external_data_ingestion":
                    raise RuntimeError(_MISSING_EDI_ERROR) from exc
                raise

            self._client = await EmailClient.create()
        return self._client

    async def _validate_account(self, client, account_email: str) -> ExecutionResult | None:
        """Return an error result if *account_email* is not active, else None."""
        active = await client.get_active_accounts()
        active_emails = {a.email for a in active}
        if account_email in active_emails:
            return None
        return ExecutionResult(
            success=False,
            error=(
                f"Account {account_email!r} is not active. "
                f"Active accounts: {sorted(active_emails)}"
            ),
        )

    # ── Dispatch ──────────────────────────────────────────────────

    async def execute(
        self, action: str, params: dict, credentials: dict | None = None,
    ) -> ExecutionResult:
        try:
            client = await self._get_client()
        except (ConnectionError, FileNotFoundError, RuntimeError, ValueError) as exc:
            return ExecutionResult(
                success=False,
                error=f"EDI email service not available: {exc}",
            )

        if action in _ACCOUNT_ACTIONS:
            return await self._dispatch_account_action(client, action, params)
        if action in _MESSAGE_ACTIONS:
            return await self._dispatch_message_action(client, action, params)

        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    async def _dispatch_account_action(
        self, client, action: str, params: dict,
    ) -> ExecutionResult:
        """Actions keyed by account_email (send, read, search)."""
        account_email = params.get("account_email")
        if not account_email:
            try:
                active = await client.get_active_accounts()
                emails = [a.email for a in active]
            except Exception:
                emails = []
            return ExecutionResult(
                success=False,
                error=f"account_email is required. Active accounts: {emails}",
            )

        err = await self._validate_account(client, account_email)
        if err:
            return err

        if action == ActionType.SEND_EMAIL.value:
            return await self._send(client, account_email, params)
        if action == ActionType.READ_EMAIL.value:
            return await self._read(client, account_email, params)
        if action == ActionType.SEARCH_EMAIL.value:
            return await self._search(client, account_email, params)

        return ExecutionResult(success=False, error=f"Unknown account action: {action}")

    async def _dispatch_message_action(
        self, client, action: str, params: dict,
    ) -> ExecutionResult:
        """Actions keyed by rfc_message_id (get, reply, forward, etc.)."""
        message_id = params.get("rfc_message_id")
        if not message_id:
            return ExecutionResult(
                success=False, error="rfc_message_id is required",
            )

        if action == ActionType.GET_EMAIL.value:
            return await self._get_email(client, message_id, params)
        if action == ActionType.REPLY_EMAIL.value:
            return await self._reply(client, message_id, params)
        if action == ActionType.FORWARD_EMAIL.value:
            return await self._forward(client, message_id, params)
        if action == ActionType.MARK_READ_EMAIL.value:
            return await self._mark_read(client, message_id, params)
        if action == ActionType.MOVE_EMAIL.value:
            return await self._move(client, message_id, params)
        if action == ActionType.DELETE_EMAIL.value:
            return await self._delete(client, message_id)
        if action == ActionType.DOWNLOAD_ATTACHMENT.value:
            return await self._download_attachment(client, message_id, params)

        return ExecutionResult(success=False, error=f"Unknown message action: {action}")

    # ── Account-based handlers ────────────────────────────────────

    @staticmethod
    async def _send(client, account_email: str, params: dict) -> ExecutionResult:
        to = params.get("to", [])
        if isinstance(to, str):
            to = [to]
        if not to:
            return ExecutionResult(success=False, error="No recipients provided")

        result = await client.send(
            account_email,
            to=to,
            subject=params.get("subject", ""),
            body=params.get("body", ""),
            cc=params.get("cc"),
            html=params.get("html_body", ""),
        )
        if result.success:
            return ExecutionResult(
                success=True,
                data={
                    "to": to,
                    "subject": params.get("subject", ""),
                    "rfc_message_id": result.message_id,
                    "sent": True,
                },
            )
        return ExecutionResult(success=False, error=result.error)

    @staticmethod
    async def _read(client, account_email: str, params: dict) -> ExecutionResult:
        from external_data_ingestion.email.models import AccountNotFoundError

        mailbox = params.get("mailbox", "INBOX")
        limit = params.get("limit", 10)
        unread_only = params.get("unread_only", False)

        try:
            emails = await client.get_recent(
                account_email, mailbox=mailbox, limit=limit,
            )
        except AccountNotFoundError as exc:
            return ExecutionResult(success=False, error=str(exc))

        if unread_only:
            emails = [e for e in emails if "\\Seen" not in e.flags]

        messages = [
            {
                "rfc_message_id": e.message_id,
                "subject": e.subject,
                "sender": e.sender_raw or e.sender_email,
                "date": e.date,
                "read": "\\Seen" in e.flags,
            }
            for e in emails
        ]
        return ExecutionResult(
            success=True,
            data={"messages": messages, "count": len(messages)},
        )

    @staticmethod
    async def _search(client, account_email: str, params: dict) -> ExecutionResult:
        from external_data_ingestion.email.models import AccountNotFoundError

        query = params.get("query", "")
        if not query:
            return ExecutionResult(success=False, error="No search query provided")

        limit = params.get("limit", 10)
        mailbox = params.get("mailbox")

        try:
            results = await client.search(
                query,
                account_email=account_email,
                mailbox=mailbox,
                limit=limit,
            )
        except AccountNotFoundError as exc:
            return ExecutionResult(success=False, error=str(exc))

        items = [
            {
                "rfc_message_id": e.message_id,
                "subject": e.subject,
                "sender": e.sender_raw or e.sender_email,
                "date": e.date,
            }
            for e in results
        ]
        return ExecutionResult(
            success=True,
            data={"results": items, "query": query, "count": len(items)},
        )

    # ── Message-based handlers ────────────────────────────────────

    @staticmethod
    async def _get_email(client, message_id: str, params: dict) -> ExecutionResult:
        headers_only = params.get("headers_only", False)
        email = await client.get_email(message_id, headers_only=headers_only)
        if not email:
            return ExecutionResult(success=False, error=f"Email {message_id!r} not found")

        attachments = await client.list_attachments(message_id)

        return ExecutionResult(
            success=True,
            data={
                "rfc_message_id": email.message_id,
                "account_email": email.account_email,
                "subject": email.subject,
                "sender": email.sender_raw or email.sender_email,
                "to": email.to_recipients,
                "cc": email.cc_recipients,
                "date": email.date,
                "body": email.body_plain,
                "body_html": email.body_html,
                "has_attachments": email.has_attachments,
                "attachments": [
                    {
                        "filename": a.filename,
                        "content_type": a.content_type,
                        "size_bytes": a.size_bytes,
                    }
                    for a in attachments
                    if not a.is_inline
                ],
                "mailbox": email.mailbox,
                "read": "\\Seen" in email.flags,
            },
        )

    @staticmethod
    async def _reply(client, message_id: str, params: dict) -> ExecutionResult:
        body = params.get("body", "")
        if not body:
            return ExecutionResult(success=False, error="Reply body is required")

        result = await client.reply(
            message_id,
            body=body,
            html=params.get("html_body", ""),
            reply_all=params.get("reply_all", False),
        )
        if result.success:
            mid = result.message_id if hasattr(result, "message_id") else None
            return ExecutionResult(
                success=True,
                data={"rfc_message_id": mid, "replied_to": message_id},
            )
        return ExecutionResult(success=False, error=result.error)

    @staticmethod
    async def _forward(client, message_id: str, params: dict) -> ExecutionResult:
        to = params.get("to", [])
        if isinstance(to, str):
            to = [to]
        if not to:
            return ExecutionResult(success=False, error="No recipients provided for forward")

        result = await client.forward(
            message_id,
            to=to,
            body=params.get("body", ""),
            html=params.get("html_body", ""),
        )
        if result.success:
            mid = result.message_id if hasattr(result, "message_id") else None
            return ExecutionResult(
                success=True,
                data={"rfc_message_id": mid, "forwarded_from": message_id, "to": to},
            )
        return ExecutionResult(success=False, error=result.error)

    @staticmethod
    async def _mark_read(client, message_id: str, params: dict) -> ExecutionResult:
        read = params.get("read", True)
        await client.mark_read(message_id, read=read)
        return ExecutionResult(
            success=True,
            data={"rfc_message_id": message_id, "read": read},
        )

    @staticmethod
    async def _move(client, message_id: str, params: dict) -> ExecutionResult:
        to_folder = params.get("to_folder", "")
        if not to_folder:
            return ExecutionResult(success=False, error="to_folder is required")
        await client.move(message_id, to_folder)
        return ExecutionResult(
            success=True,
            data={"rfc_message_id": message_id, "moved_to": to_folder},
        )

    @staticmethod
    async def _delete(client, message_id: str) -> ExecutionResult:
        await client.delete(message_id)
        return ExecutionResult(
            success=True,
            data={"rfc_message_id": message_id, "deleted": True},
        )

    _DOWNLOADS_DIR = Path.home() / ".intentframe" / "downloads" / "email"

    @classmethod
    async def _download_attachment(
        cls, client, message_id: str, params: dict,
    ) -> ExecutionResult:
        filename = params.get("filename", "")
        if not filename:
            return ExecutionResult(success=False, error="filename is required")

        data = await client.download_attachment(message_id, filename)
        if data is None:
            return ExecutionResult(
                success=False,
                error=f"Attachment {filename!r} not found on email {message_id!r}",
            )

        safe_name = filename.replace("/", "_").replace("\\", "_") or "attachment.bin"
        downloads = cls._DOWNLOADS_DIR
        downloads.mkdir(parents=True, exist_ok=True)
        dest = downloads / safe_name
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            counter = 1
            while dest.exists():
                dest = downloads / f"{stem}_{counter}{suffix}"
                counter += 1
        dest.write_bytes(data)

        vfs_path = f"/home/.intentframe/downloads/email/{dest.name}"

        return ExecutionResult(
            success=True,
            data={
                "rfc_message_id": message_id,
                "filename": filename,
                "size_bytes": len(data),
                "path": vfs_path,
            },
        )

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Email actions are irreversible")
