"""Email action bundle."""

from __future__ import annotations

import asyncio
import fnmatch
import re
from typing import Any

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.actions.email.constraints import EmailConstraints
from intentframe_native_bundles.actions.email.enrich import EMAIL_MESSAGE_ACTIONS, enrich_intent
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleContext,
    BundlePhaseOutcome,
)

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_ENRICHER_RESOLVED = frozenset({ActionType.REPLY_EMAIL.value})

_EMAIL_READ_ACTIONS = frozenset({
    ActionType.READ_EMAIL.value,
    ActionType.SEARCH_EMAIL.value,
    ActionType.GET_EMAIL.value,
    ActionType.DOWNLOAD_ATTACHMENT.value,
})

_EMAIL_BUNDLE_ACTIONS: frozenset[str] = frozenset({
    ActionType.SEND_EMAIL.value,
    ActionType.REPLY_EMAIL.value,
    ActionType.FORWARD_EMAIL.value,
    ActionType.MARK_READ_EMAIL.value,
    ActionType.MOVE_EMAIL.value,
    ActionType.DELETE_EMAIL.value,
}) | _EMAIL_READ_ACTIONS


class EmailActionBundle(ActionBundle):
    bundle_id = "email"
    action_ids = _EMAIL_BUNDLE_ACTIONS
    passive_read_action_ids = _EMAIL_READ_ACTIONS

    def __init__(self) -> None:
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()
        self._closed = False

    async def _get_client(self) -> Any:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    if self._closed:
                        raise RuntimeError("EmailActionBundle is closed")
                    from external_data_ingestion.email.client import EmailClient

                    self._client = await EmailClient.create()
        return self._client

    async def enrich(
        self,
        intent: IntentFrame,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del verbose
        if intent.action.value in EMAIL_MESSAGE_ACTIONS:
            client = await self._get_client()
            ctx.enriched_intent = await enrich_intent(intent, client=client)
        return BundlePhaseOutcome.continue_(ctx)

    async def aclose(self) -> None:
        self._closed = True
        client, self._client = self._client, None
        if client is not None:
            await client.close()

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            EmailConstraints.model_validate(action_permission.constraints)

    def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del verbose
        if action_permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = EmailConstraints.model_validate(action_permission.constraints)
        passed, reason = self._check(intent, constraints)
        if not passed:
            return BundlePhaseOutcome.block(
                ctx,
                reason=f"Constraint violation: {reason}",
                matched_gate="constraint",
            )
        return BundlePhaseOutcome.continue_(ctx)

    def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = EmailConstraints.model_validate(action_permission.constraints)
        recipients = constraints.allowed_recipients
        if len(recipients) <= 10:
            return f"Allowed recipients: {', '.join(recipients)}"
        return f"Allowed recipients: {len(recipients)} addresses configured"

    @staticmethod
    def _extract_emails(value: str) -> list[str]:
        return _EMAIL_RE.findall(value)

    def _check(
        self,
        intent: IntentFrame,
        constraints: EmailConstraints,
    ) -> tuple[bool, str]:
        data = intent.data or {}
        action = intent.action.value
        raw_to = str(data.get("to", "")).strip()
        recipients = self._extract_emails(raw_to) if raw_to else []
        if not recipients:
            if action in _ENRICHER_RESOLVED:
                return False, (
                    "Could not determine reply recipient — email enrichment "
                    "likely failed (bad or hallucinated rfc_message_id?)"
                )
            return False, "No recipient email address specified"
        for addr in recipients:
            if not any(fnmatch.fnmatch(addr, pat) for pat in constraints.allowed_recipients):
                return False, f"Recipient '{addr}' not in allowed recipients"
        return True, ""
