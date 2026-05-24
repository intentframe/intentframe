"""Domain bundle routing and policy validation."""

from __future__ import annotations

import pytest

from intentframe_action_bundle.bundles.register import ensure_bundles_registered
from intentframe_action_bundle.domain_routes import DOMAIN_ROUTES
from intentframe_bundle_sdk.registry import (
    domains_for_action,
    routed_domain_ids,
    validate_policy_domain_constraints,
)
from policy_registry.domains.deletion import DeletionConstraints
from policy_registry.domains.finance import FinanceConstraints


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_bundles_registered()


def test_domain_routes_cover_legacy_actions() -> None:
    assert "PAY_INVOICE" in DOMAIN_ROUTES["finance"]
    assert "DELETE_FILE" in DOMAIN_ROUTES["deletion"]
    assert domains_for_action("PAY_INVOICE") == ("finance",)
    assert "deletion" in domains_for_action("DELETE_FILE")


def test_domain_routes_allow_multiple_domains_per_action() -> None:
    """Manifest may map several domain ids to the same action id."""
    overlapping = {
        "finance": frozenset({"PAY_INVOICE"}),
        "spending": frozenset({"PAY_INVOICE"}),
    }
    action_to_domains: dict[str, set[str]] = {}
    for domain_id, action_ids in overlapping.items():
        for action_id in action_ids:
            action_to_domains.setdefault(action_id, set()).add(domain_id)
    assert action_to_domains["PAY_INVOICE"] == {"finance", "spending"}


def test_validate_policy_domain_constraints_requires_registered_bundle() -> None:
    with pytest.raises(ValueError, match="no registered DomainBundle"):
        validate_policy_domain_constraints(
            {"ghost_domain": FinanceConstraints(max_amount=1.0)},
        )


def test_validate_policy_domain_constraints_accepts_configured_domains() -> None:
    validate_policy_domain_constraints(
        {
            "finance": FinanceConstraints(max_amount=5000.0),
            "deletion": DeletionConstraints(block_irreversible=True),
        }
    )


def test_routed_domain_ids_match_manifest() -> None:
    assert routed_domain_ids() == frozenset(DOMAIN_ROUTES)
