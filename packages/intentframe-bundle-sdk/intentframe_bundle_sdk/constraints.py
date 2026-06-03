"""Render opaque policy constraint dicts via registered action bundles."""

from __future__ import annotations

from typing import Any

from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.registry import action_bundle_for
from intentframe_bundle_sdk.types import ActionPermission, action_permission_from_policy


async def describe_permission_constraints(
    bundle: ActionBundle,
    action_permission: ActionPermission,
) -> str:
    """Render constraints when the responsible bundle is already resolved."""
    if action_permission.constraints is None:
        return "No specific constraints"
    described = await bundle.describe_constraints(action_permission)
    if described is not None:
        return described
    return str(action_permission.constraints)


async def describe_action_constraints(
    action_id: str,
    constraints: dict[str, Any] | None,
    *,
    safe: bool = True,
) -> str:
    """Render opaque policy constraints via the responsible action bundle.

    Requires bundles to be registered (``ensure_loaded``) before call.
    """
    if constraints is None:
        return "No specific constraints"
    bundle = action_bundle_for(action_id)
    if bundle is None:
        return str(constraints)
    permission = ActionPermission(safe=safe, constraints=constraints)
    return await describe_permission_constraints(bundle, permission)


async def describe_action_constraints_from_policy(
    action_id: str,
    permission: Any,
) -> str:
    """Render constraints from a policy-registry ``ActionPermission``."""
    sdk_permission = action_permission_from_policy(permission)
    return await describe_action_constraints(
        action_id,
        sdk_permission.constraints,
        safe=sdk_permission.safe,
    )
