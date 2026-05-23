"""HTTP API action bundle."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle
from policy_registry.constraints.api import ApiConstraints


class ApiActionBundle(ActionBundle):
    bundle_id = "api"
    action_ids = frozenset({
        ActionType.HTTP_GET.value,
        ActionType.HTTP_POST.value,
    })
    passive_read_action_ids = frozenset({ActionType.HTTP_GET.value})
    constraint_type = ApiConstraints
