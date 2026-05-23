"""Browser action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle
from policy_registry.constraints.browser import BrowserConstraints


class BrowserActionBundle(ActionBundle):
    bundle_id = "browser"
    action_ids = frozenset({
        ActionType.GET_PAGE_CONTENT.value,
        ActionType.OPEN_URL.value,
    })
    passive_read_action_ids = frozenset({ActionType.GET_PAGE_CONTENT.value})
    constraint_type = BrowserConstraints
