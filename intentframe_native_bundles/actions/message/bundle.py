"""Message action bundle."""

from __future__ import annotations

import fnmatch

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.actions.message.constraints import MessageConstraints
from intentframe_native_bundles.platform.contacts_client import PlatformContactsClient
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleContext,
    BundlePhaseOutcome,
)


class MessageActionBundle(ActionBundle):
    bundle_id = "message"
    action_ids = frozenset({
        ActionType.READ_MESSAGES.value,
        ActionType.SEND_MESSAGE.value,
    })
    passive_read_action_ids = frozenset({ActionType.READ_MESSAGES.value})

    def __init__(self) -> None:
        self._contacts = PlatformContactsClient()

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            MessageConstraints.model_validate(action_permission.constraints)

    async def aclose(self) -> None:
        self._contacts.invalidate()

    async def enforce_constraints(
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
        constraints = MessageConstraints.model_validate(action_permission.constraints)

        # Resolve dynamic contact sources — constraint check, not enrichment.
        allowed = list(constraints.allowed_contacts)
        if (
            intent.action.value == ActionType.SEND_MESSAGE.value
            and constraints.contact_sources
        ):
            resolved = await self._contacts.resolve_sources(constraints.contact_sources)
            allowed = list(set(allowed) | set(resolved))

        contact = (intent.data or {}).get("to", intent.target)
        for pattern in allowed:
            if fnmatch.fnmatch(str(contact), pattern):
                return BundlePhaseOutcome.continue_(ctx)
        return BundlePhaseOutcome.block(
            ctx,
            reason=f"Constraint violation: Contact '{contact}' not in allowed contacts",
            matched_gate="constraint",
        )

    async def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is not None:
            constraints = MessageConstraints.model_validate(action_permission.constraints)
            contacts = constraints.allowed_contacts
            if len(contacts) <= 10:
                return f"Allowed contacts: {', '.join(contacts)}"
            return f"Allowed contacts: {len(contacts)} contacts configured"
        return None
