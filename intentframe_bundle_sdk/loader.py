"""Plugin package loader and startup policy validation.

Conventions enforced here and in bundle hooks:

- Bundles never receive ``UserContext``, ``UserPolicy``, or another action's
  permission slice — only a per-action :class:`ActionPermission`.
- Parsed constraints must not be cached on bundle instances (supports hot reload).
- :class:`DeterministicRunner` is the sole runtime caller of bundle/domain hooks;
  substrate components consume prepared :class:`BundleAIContext` data only.
- Each plugin package exposes ``register_bundles(registry)``; importing the
  package must not register bundles as a side effect.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from intentframe_bundle_sdk.registry import (
    action_bundle_for,
    all_action_bundles,
    validate_policy_domain_constraints,
)
from intentframe_bundle_sdk.trace import traced_call
from intentframe_bundle_sdk.types import action_permission_from_policy

if TYPE_CHECKING:
    from intentframe_bundle_sdk.action import ActionBundle
    from policy_registry.models import UserPolicy

_LOADED_PACKAGES: frozenset[str] | None = None


def ensure_loaded(packages: list[str]) -> list[ActionBundle]:
    """Load plugin packages into the global SDK registry (idempotent).

    For each package: ``importlib.import_module``; require ``register_bundles``;
    call ``module.register_bundles(registry)`` with the SDK registry module.

    Raises:
        ImportError: Package missing or lacks ``register_bundles``.
        RuntimeError: Called again with a different package set than the first load.
    """
    global _LOADED_PACKAGES

    normalized = frozenset(packages)
    if not normalized:
        raise ValueError("ensure_loaded requires at least one package name")

    if _LOADED_PACKAGES is not None:
        if _LOADED_PACKAGES != normalized:
            raise RuntimeError(
                f"bundles already loaded for {sorted(_LOADED_PACKAGES)!r}; "
                f"cannot reload with {sorted(normalized)!r}"
            )
        return list(all_action_bundles())

    import intentframe_bundle_sdk.registry as registry

    for package in sorted(normalized):
        try:
            module = importlib.import_module(package)
        except ImportError as exc:
            raise ImportError(
                f"failed to import bundle package {package!r}"
            ) from exc
        register = getattr(module, "register_bundles", None)
        if register is None:
            raise ImportError(
                f"bundle package {package!r} has no register_bundles(registry) entry point"
            )
        register(registry)

    _LOADED_PACKAGES = normalized
    return list(all_action_bundles())


def validate_policy_against_registry(policy: UserPolicy) -> None:
    """Fail closed when seeded policy references bundles that cannot enforce it."""
    for action_id in policy.allowed_actions:
        bundle = action_bundle_for(action_id)
        if bundle is None:
            raise ValueError(
                f"allowed action {action_id!r} has no registered ActionBundle"
            )

    for action_id, perm in policy.allowed_actions.items():
        if perm.constraints is None:
            continue
        bundle = action_bundle_for(action_id)
        assert bundle is not None
        traced_call(
            bundle.validate_constraints, action_permission_from_policy(perm),
            lane="boot",
            trace_id=f"boot:{bundle.bundle_id}:{action_id}",
            phase="validate_constraints",
        )

    if policy.domain_constraints:
        validate_policy_domain_constraints(policy.domain_constraints)
