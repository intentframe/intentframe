"""Bundle registration and lookup."""

from __future__ import annotations

from typing import Any

from intentframe_bundle_sdk.action import ActionBundle, CheckerOnlyActionBundle, NullActionBundle
from intentframe_bundle_sdk.domain import DomainBundle

_ACTION_BY_ID: dict[str, ActionBundle] = {}
_CHECKER_BY_TYPE: dict[type, ActionBundle] = {}
_ACTION_INSTANCES: list[ActionBundle] = []
_DOMAIN_BY_ID: dict[str, DomainBundle] = {}
_ACTION_TO_DOMAINS: dict[str, tuple[str, ...]] = {}
_ROUTED_DOMAIN_IDS: frozenset[str] = frozenset()
_NULL = NullActionBundle()


def register_action_bundle(bundle: ActionBundle) -> ActionBundle:
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
    if bundle.constraint_type is not None:
        _CHECKER_BY_TYPE[bundle.constraint_type] = bundle
    return bundle


def register_domain_bundle(bundle: DomainBundle) -> DomainBundle:
    if bundle.domain_id in _DOMAIN_BY_ID:
        raise ValueError(f"duplicate domain_id {bundle.domain_id!r}")
    _DOMAIN_BY_ID[bundle.domain_id] = bundle
    return bundle


def register_domain_routes(routes: dict[str, frozenset[str]]) -> None:
    """Declare which action ids each domain applies to (routing metadata).

    ``routes`` maps ``domain_id`` → action ids. Multiple domains may apply
    to the same action. Every ``domain_id`` must already be registered via
    :func:`register_domain_bundle`.
    """
    global _ROUTED_DOMAIN_IDS

    unknown = set(routes) - set(_DOMAIN_BY_ID)
    if unknown:
        raise ValueError(
            f"domain routes reference unregistered domain_id(s): {sorted(unknown)}"
        )

    action_map: dict[str, list[str]] = {}
    for domain_id, action_ids in routes.items():
        for action_id in action_ids:
            action_map.setdefault(action_id, [])
            if domain_id not in action_map[action_id]:
                action_map[action_id].append(domain_id)

    _ACTION_TO_DOMAINS.clear()
    for action_id, domain_ids in action_map.items():
        _ACTION_TO_DOMAINS[action_id] = tuple(sorted(domain_ids))

    _ROUTED_DOMAIN_IDS = frozenset(routes)


def validate_policy_domain_constraints(
    domain_constraints: dict[str, Any],
    *,
    validate_shapes: bool = True,
) -> None:
    """Fail closed when policy declares domain constraints that cannot be enforced.

    Raises:
        ValueError: domain key has no registered bundle, no route, or invalid shape.
    """
    for domain_id, constraints in domain_constraints.items():
        if domain_id not in _DOMAIN_BY_ID:
            raise ValueError(
                f"domain_constraints[{domain_id!r}] has no registered DomainBundle"
            )
        if domain_id not in _ROUTED_DOMAIN_IDS:
            raise ValueError(
                f"domain_constraints[{domain_id!r}] has no domain route — "
                "cannot enforce at runtime"
            )
        if validate_shapes and constraints is not None:
            raw = (
                constraints
                if isinstance(constraints, dict)
                else constraints.model_dump(mode="python")
            )
            _DOMAIN_BY_ID[domain_id].validate_constraints(raw)


def action_bundle_for(action_id: str, permission=None) -> ActionBundle:
    if action_id in _ACTION_BY_ID:
        return _ACTION_BY_ID[action_id]
    if permission is not None and permission.constraints is not None:
        checker = _CHECKER_BY_TYPE.get(type(permission.constraints))
        if checker is not None:
            return checker
    return _NULL


def domain_bundle_for(domain_id: str) -> DomainBundle | None:
    return _DOMAIN_BY_ID.get(domain_id)


def domains_for_action(action_id: str) -> tuple[str, ...]:
    return _ACTION_TO_DOMAINS.get(action_id, ())


def all_action_bundles() -> tuple[ActionBundle, ...]:
    return tuple(_ACTION_INSTANCES)


def all_domain_bundles() -> tuple[DomainBundle, ...]:
    return tuple(_DOMAIN_BY_ID.values())


def registered_domain_ids() -> frozenset[str]:
    return frozenset(_DOMAIN_BY_ID)


def routed_domain_ids() -> frozenset[str]:
    return _ROUTED_DOMAIN_IDS


def registered_checker_constraint_types() -> frozenset[type]:
    """Constraint types with a registered action bundle (for invariant tests)."""
    return frozenset(_CHECKER_BY_TYPE.keys())


def all_passive_read_action_ids() -> frozenset[str]:
    """Union of ``passive_read_action_ids`` across registered action bundles."""
    result: set[str] = set()
    for bundle in _ACTION_INSTANCES:
        result.update(bundle.passive_read_action_ids)
    return frozenset(result)
