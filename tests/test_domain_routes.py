"""Domain bundle routing and policy validation."""

from __future__ import annotations

import pytest

from action_registry.types import ACTION_DOMAINS, ActionType, DomainType
from intentframe_action_bundle import ensure_bundles_registered
from intentframe_bundle_sdk.registry import (
    domain_bundle_for,
    validate_policy_domain_constraints,
)


@pytest.fixture(autouse=True)
def _register_bundles() -> None:
    ensure_bundles_registered()


def test_action_domains_cover_finance_and_deletion() -> None:
    assert ACTION_DOMAINS[ActionType.PAY_INVOICE] == DomainType.FINANCE
    assert ACTION_DOMAINS[ActionType.DELETE_FILE] == DomainType.DELETION
    assert domain_bundle_for(DomainType.FINANCE) is not None
    assert domain_bundle_for(DomainType.DELETION) is not None


def test_validate_policy_domain_constraints_requires_registered_bundle() -> None:
    with pytest.raises(ValueError, match="no registered DomainBundle"):
        validate_policy_domain_constraints({"ghost_domain": {"max_amount": 1.0}})


def test_validate_policy_domain_constraints_accepts_configured_domains() -> None:
    validate_policy_domain_constraints(
        {
            "finance": {"max_amount": 5000.0},
            "deletion": {"block_irreversible": True},
        }
    )
