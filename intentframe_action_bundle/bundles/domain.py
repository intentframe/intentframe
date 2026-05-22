"""Domain bundles — finance and deletion."""

from __future__ import annotations

from action_registry.types import ACTION_DOMAINS, DomainType
from intentframe_core.types import IntentFrame, UserContext

from intentframe_components.guardian.domains.deletion import DeletionModule
from intentframe_components.guardian.domains.finance import FinanceModule
from intentframe_bundle_sdk.domain import DomainBundle


class FinanceDomainBundle(DomainBundle):
    domain_id = "finance"
    action_ids = frozenset(
        action.value for action, domain in ACTION_DOMAINS.items()
        if domain is DomainType.FINANCE
    )
    _module = FinanceModule()

    @property
    def domain_type(self) -> DomainType:
        return DomainType.FINANCE

    def check(self, intent: IntentFrame, user_context: UserContext) -> tuple[bool, str]:
        dc_map = user_context.domain_constraints or {}
        constraints = dc_map.get(self.domain_id)
        if constraints is None:
            return True, ""
        return self._module.check(intent, constraints)


class DeletionDomainBundle(DomainBundle):
    domain_id = "deletion"
    action_ids = frozenset(
        action.value for action, domain in ACTION_DOMAINS.items()
        if domain is DomainType.DELETION
    )
    _module = DeletionModule()

    @property
    def domain_type(self) -> DomainType:
        return DomainType.DELETION

    def check(self, intent: IntentFrame, user_context: UserContext) -> tuple[bool, str]:
        dc_map = user_context.domain_constraints or {}
        constraints = dc_map.get(self.domain_id)
        if constraints is None:
            return True, ""
        return self._module.check(intent, constraints)
