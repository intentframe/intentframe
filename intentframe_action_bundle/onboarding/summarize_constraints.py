"""Per-constraint summaries for onboarding prompts."""

from __future__ import annotations

from intentframe_action_bundle import _ensure_first_party_bundles_loaded
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.types import ActionPermission, action_permission_from_policy
from policy_registry.models import ActionPermission as PolicyActionPermission


def summarize_constraints_for_onboarding(
    action: str,
    constraints: dict,
) -> str:
    """Conceptual constraint brief for the onboarding meta-LLM."""
    _ensure_first_party_bundles_loaded()
    bundle = action_bundle_for(action)
    if bundle is None:
        return str(constraints)
    permission = action_permission_from_policy(
        PolicyActionPermission(safe=True, constraints=constraints)
    )
    described = bundle.describe_constraints(permission)
    return described if described is not None else str(constraints)
