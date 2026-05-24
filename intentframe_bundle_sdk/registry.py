"""Bundle registration and lookup."""

from __future__ import annotations

from typing import Any

from action_registry.types import DomainType

from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.domain import DomainBundle

_ACTION_BY_ID: dict[str, ActionBundle] = {}
_ACTION_INSTANCES: list[ActionBundle] = []
_DOMAIN_BY_TYPE: dict[DomainType, DomainBundle] = {}


def register_action_bundle(bundle: ActionBundle) -> ActionBundle:
    if not bundle.bundle_id:
        raise ValueError("bundle_id must be non-empty")
    if not bundle.action_ids:
        raise ValueError(f"bundle {bundle.bundle_id!r}: action_ids must be non-empty")
    extra_passive = bundle.passive_read_action_ids - bundle.action_ids
    if extra_passive:
        raise ValueError(
            f"bundle {bundle.bundle_id!r}: passive_read_action_ids must be a "
            f"subset of action_ids; unknown: {sorted(extra_passive)}"
        )
    _ACTION_INSTANCES.append(bundle)
    for action_id in bundle.action_ids:
        if action_id in _ACTION_BY_ID:
            existing = _ACTION_BY_ID[action_id]
            raise ValueError(
                f"duplicate action_id {action_id!r}: "
                f"{existing.bundle_id!r} and {bundle.bundle_id!r}"
            )
        _ACTION_BY_ID[action_id] = bundle
    return bundle


def register_domain_bundle(bundle: DomainBundle) -> DomainBundle:
    if not bundle.bundle_id:
        raise ValueError("domain bundle_id must be non-empty")
    if bundle.domain_type in _DOMAIN_BY_TYPE:
        existing = _DOMAIN_BY_TYPE[bundle.domain_type]
        raise ValueError(
            f"duplicate domain_type {bundle.domain_type!r}: "
            f"{existing.bundle_id!r} and {bundle.bundle_id!r}"
        )
    _DOMAIN_BY_TYPE[bundle.domain_type] = bundle
    return bundle


def validate_policy_domain_constraints(
    domain_constraints: dict[str, Any],
    *,
    validate_shapes: bool = True,
) -> None:
    """Fail closed when policy declares domain constraints that cannot be enforced."""
    for domain_id, constraints in domain_constraints.items():
        try:
            domain_type = DomainType(domain_id)
        except ValueError as exc:
            raise ValueError(
                f"domain_constraints[{domain_id!r}] has no registered DomainBundle"
            ) from exc
        bundle = _DOMAIN_BY_TYPE.get(domain_type)
        if bundle is None:
            raise ValueError(
                f"domain_constraints[{domain_id!r}] has no registered DomainBundle"
            )
        if validate_shapes and constraints is not None:
            bundle.validate(constraints)


def action_bundle_for(action_id: str) -> ActionBundle | None:
    return _ACTION_BY_ID.get(action_id)


def domain_bundle_for(domain_type: DomainType | str) -> DomainBundle | None:
    if isinstance(domain_type, str):
        try:
            domain_type = DomainType(domain_type)
        except ValueError:
            return None
    return _DOMAIN_BY_TYPE.get(domain_type)


def all_action_bundles() -> tuple[ActionBundle, ...]:
    return tuple(_ACTION_INSTANCES)


def all_domain_bundles() -> tuple[DomainBundle, ...]:
    return tuple(_DOMAIN_BY_TYPE.values())


def all_passive_read_action_ids() -> frozenset[str]:
    """Union of ``passive_read_action_ids`` across registered action bundles."""
    result: set[str] = set()
    for bundle in _ACTION_INSTANCES:
        result.update(bundle.passive_read_action_ids)
    return frozenset(result)
