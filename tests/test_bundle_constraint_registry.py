"""Startup invariants for bundle constraint enforcement coverage."""

from __future__ import annotations

import inspect

from tests._bundle_loader import ensure_test_bundles_loaded
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.registry import action_bundle_for, all_action_bundles
from jarvis.policies import builtin_policy_path
from policy_registry.seeds.loader import load_policy_seed


def test_every_seeded_allowed_action_resolves_to_bundle() -> None:
    ensure_test_bundles_loaded()
    policy = load_policy_seed(
        builtin_policy_path("user"), user_id="u", agent_id="jarvis"
    )
    missing: list[str] = []
    for action_id in policy.allowed_actions:
        if action_bundle_for(action_id) is None:
            missing.append(action_id)
    assert missing == [], f"allowed actions without bundles: {missing}"


def test_constrained_seeded_actions_override_enforce_constraints() -> None:
    ensure_test_bundles_loaded()
    policy = load_policy_seed(
        builtin_policy_path("user"), user_id="u", agent_id="jarvis"
    )
    default_enforce = ActionBundle.enforce_constraints
    for action_id, perm in policy.allowed_actions.items():
        if perm.constraints is None:
            continue
        bundle = action_bundle_for(action_id)
        assert bundle is not None
        assert bundle.enforce_constraints is not default_enforce


def test_all_registered_bundles_have_non_empty_ids() -> None:
    ensure_test_bundles_loaded()
    for bundle in all_action_bundles():
        assert bundle.bundle_id
        assert bundle.action_ids
        for name in (
            "prepare_evidence",
            "enrich",
            "validate_constraints",
            "enforce_constraints",
            "structural_gates",
            "allow_gates",
            "build_ai_context",
            "describe_constraints",
        ):
            sig = inspect.signature(getattr(bundle, name))
            assert "user_context" not in sig.parameters
