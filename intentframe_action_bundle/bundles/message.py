"""Message action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle
from policy_registry.constraints.message import MessageConstraints


class MessageActionBundle(ActionBundle):
    bundle_id = "message"
    action_ids = frozenset({
        ActionType.READ_MESSAGES.value,
        ActionType.SEND_MESSAGE.value,
    })
    passive_read_action_ids = frozenset({ActionType.READ_MESSAGES.value})
    constraint_type = MessageConstraints
