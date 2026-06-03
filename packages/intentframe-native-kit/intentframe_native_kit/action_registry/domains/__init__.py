"""
Critical-domain intent data schemas.

Each schema validates a **slice** of :attr:`~intentframe_bundle_sdk.IntentFrame.data`
for one risk domain (finance, deletion, …). Unrelated payload keys are ignored
(``extra="ignore"`` on :class:`~intentframe_bundle_sdk.DomainSchema`),
so multiple domains can apply to the same action without one exhaustive model.

``DOMAIN_SCHEMAS`` maps :class:`~intentframe_native_kit.action_registry.types.DomainType` to schema
classes. It pairs with ``ACTION_DOMAINS`` in ``intentframe_native_kit.action_registry.types``.

Who validates:
    - **Optional (author-side):** agent tools (e.g. Jarvis ``_validate_against_registry``).
    - **Authoritative (server-side):** ``check_domain_intent_shape`` in the bundle
      SDK runner, then each :class:`~intentframe_bundle_sdk.domain.DomainBundle`.

Import from ``intentframe_native_kit.action_registry.domains`` — not from ``intentframe_native_kit.action_registry`` top-level
(see ``intentframe_native_kit.action_registry.__init__``).
"""

from __future__ import annotations

from intentframe_bundle_sdk import DomainSchema

from intentframe_native_kit.action_registry.domains.deletion import DeletionIntentData
from intentframe_native_kit.action_registry.domains.finance import FinancialIntentData
from intentframe_native_kit.action_registry.types import DomainType

DOMAIN_SCHEMAS: dict[DomainType, type[DomainSchema]] = {
    DomainType.FINANCE: FinancialIntentData,
    DomainType.DELETION: DeletionIntentData,
}

__all__ = [
    "DOMAIN_SCHEMAS",
    "DeletionIntentData",
    "FinancialIntentData",
]
