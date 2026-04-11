"""
Load a test policy from the shared YAML into a UserPolicy.

Both attack and red-team test suites call ``load_test_policy()`` with their
suite-specific user_id.  The policy definition lives in one place
(demo/config/test_policy.yaml) so changes propagate to all suites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from policy_registry.domains import DOMAIN_CONSTRAINT_TYPES
from policy_registry.models import ActionPermission, SemanticIntentLimit, UserPolicy

_DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "test_policy.yaml"
)

_CONSTRAINT_TYPES: list[type] = []


def _discover_constraint_types() -> list[type]:
    """Lazily collect all concrete constraint classes from the registry."""
    if _CONSTRAINT_TYPES:
        return _CONSTRAINT_TYPES
    import policy_registry.constraints as _mod

    for name in _mod.__all__:
        cls = getattr(_mod, name, None)
        if isinstance(cls, type):
            _CONSTRAINT_TYPES.append(cls)
    return _CONSTRAINT_TYPES


def _parse_constraints(raw: dict[str, Any] | None) -> Any:
    """Match YAML keys against each constraint type's schema fields.

    A candidate class is accepted only when every key in the raw dict
    appears in the class's Pydantic model_fields, preventing types with
    all-optional fields (e.g. ApiConstraints) from swallowing unrelated data.
    """
    if raw is None:
        return None
    raw_keys = set(raw)
    for cls in _discover_constraint_types():
        if raw_keys <= set(cls.model_fields):
            return cls(**raw)
    raise ValueError(f"No matching constraint type for fields: {list(raw)}")


def load_test_policy(
    user_id: str,
    *,
    yaml_path: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> UserPolicy:
    """Build a ``UserPolicy`` from the shared test YAML.

    Args:
        user_id:   Suite-specific user identifier (e.g. "attack_tester").
        yaml_path: Override the default YAML location.
        metadata:  Optional metadata dict merged into the policy.
    """
    path = Path(yaml_path) if yaml_path else _DEFAULT_POLICY_PATH
    with open(path) as f:
        raw = yaml.safe_load(f)

    allowed_actions: dict[str, ActionPermission] = {}
    for action, perm in raw.get("allowed_actions", {}).items():
        allowed_actions[action] = ActionPermission(
            safe=perm.get("safe", False),
            constraints=_parse_constraints(perm.get("constraints")),
        )

    intent_limits = [
        SemanticIntentLimit(**lim) for lim in raw.get("intent_limits", [])
    ]

    domain_constraints: dict[str, Any] = {}
    for domain_name, dc_raw in raw.get("domain_constraints", {}).items():
        constraint_cls = DOMAIN_CONSTRAINT_TYPES.get(domain_name)
        if constraint_cls is not None:
            valid_fields = constraint_cls.model_fields.keys()
            dc_dict = {k: v for k, v in dc_raw.items() if k in valid_fields}
            domain_constraints[domain_name] = constraint_cls(**dc_dict)

    return UserPolicy(
        user_id=user_id,
        allowed_actions=allowed_actions,
        intent_limits=intent_limits,
        domain_constraints=domain_constraints,
        metadata=metadata or {},
    )
