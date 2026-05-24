"""Domain bundle routing and policy validation."""

from __future__ import annotations

import pytest

from action_registry.types import ActionType
from tests._bundle_loader import ensure_test_bundles_loaded
from intentframe_native_bundles.actions.api.bundle import ApiActionBundle
from intentframe_native_bundles.domain_routes import DOMAIN_ROUTES
from intentframe_bundle_sdk.registry import (
    action_bundle_for,
    domain_bundle_for,
    domains_for_action,
    registered_domain_ids,
    routed_domain_ids,
    validate_policy_domain_constraints,
)


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_test_bundles_loaded()


def test_pay_invoice_owned_by_api_action_bundle_not_finance_family() -> None:
    bundle = action_bundle_for(ActionType.PAY_INVOICE.value)
    assert bundle is not None
    assert isinstance(bundle, ApiActionBundle)
    assert bundle.bundle_id == "api"


def test_sdk_domain_routes_cover_finance_and_deletion() -> None:
    assert domains_for_action(ActionType.PAY_INVOICE.value) == ("finance",)
    assert domains_for_action(ActionType.DELETE_FILE.value) == ("deletion",)
    assert domain_bundle_for("finance") is not None
    assert domain_bundle_for("deletion") is not None
    assert registered_domain_ids() >= {"finance", "deletion"}
    assert routed_domain_ids() >= {"finance", "deletion"}
    assert "PAY_INVOICE" in DOMAIN_ROUTES["finance"]
    assert "DELETE_FILE" in DOMAIN_ROUTES["deletion"]


def test_validate_policy_domain_constraints_requires_registered_bundle() -> None:
    with pytest.raises(ValueError, match="no registered DomainBundle"):
        validate_policy_domain_constraints({"ghost_domain": {"max_amount": 1.0}})


def test_validate_policy_domain_constraints_requires_runtime_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import intentframe_bundle_sdk.registry as bundle_registry

    monkeypatch.setattr(bundle_registry, "_ROUTED_DOMAIN_IDS", frozenset())

    with pytest.raises(ValueError, match="has no domain route"):
        validate_policy_domain_constraints({"finance": {"max_amount": 1.0}})


def test_validate_policy_domain_constraints_accepts_configured_domains() -> None:
    validate_policy_domain_constraints(
        {
            "finance": {"max_amount": 5000.0},
            "deletion": {"block_irreversible": True},
        }
    )
