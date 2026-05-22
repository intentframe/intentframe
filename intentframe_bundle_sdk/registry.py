"""Bundle registration and lookup."""

from __future__ import annotations

from intentframe_bundle_sdk.action import ActionBundle, CheckerOnlyActionBundle, NullActionBundle
from intentframe_bundle_sdk.domain import DomainBundle

_ACTION_BY_ID: dict[str, ActionBundle] = {}
_CHECKER_BY_TYPE: dict[type, ActionBundle] = {}
_ACTION_INSTANCES: list[ActionBundle] = []
_DOMAIN_BY_TYPE: dict[str, DomainBundle] = {}
_NULL = NullActionBundle()


def register_action_bundle(bundle: ActionBundle) -> ActionBundle:
    _ACTION_INSTANCES.append(bundle)
    for action_id in bundle.action_ids:
        _ACTION_BY_ID[action_id] = bundle
    if bundle.constraint_type is not None:
        _CHECKER_BY_TYPE[bundle.constraint_type] = bundle
    return bundle


def register_domain_bundle(bundle: DomainBundle) -> DomainBundle:
    _DOMAIN_BY_TYPE[bundle.domain_type.value] = bundle
    return bundle


def action_bundle_for(action_id: str, permission=None) -> ActionBundle:
    if action_id in _ACTION_BY_ID:
        return _ACTION_BY_ID[action_id]
    if permission is not None and permission.constraints is not None:
        checker = _CHECKER_BY_TYPE.get(type(permission.constraints))
        if checker is not None:
            return checker
    return _NULL


def domain_bundle_for(domain_value: str) -> DomainBundle | None:
    return _DOMAIN_BY_TYPE.get(domain_value)


def all_action_bundles() -> tuple[ActionBundle, ...]:
    return tuple(_ACTION_INSTANCES)


def all_domain_bundles() -> tuple[DomainBundle, ...]:
    return tuple(_DOMAIN_BY_TYPE.values())
