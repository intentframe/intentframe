"""Finance action bundle — PAY_INVOICE and related API-category financial actions."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_bundle_sdk.action import ActionBundle
from policy_registry.constraints.api import ApiConstraints


class FinanceActionBundle(ActionBundle):
    bundle_id = "finance"
    action_ids = frozenset({ActionType.PAY_INVOICE.value})
    constraint_type = ApiConstraints
