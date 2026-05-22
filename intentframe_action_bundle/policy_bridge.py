"""Policy bridge — connect UserPolicy allowed_actions to bundle manifests."""

from __future__ import annotations

from intentframe_action_bundle.manifest import ActionBundleManifest, manifest_for


def bundle_for_action(action_id: str) -> ActionBundleManifest | None:
    """Return bundle manifest metadata for an action id, if registered."""
    return manifest_for(action_id)


def checker_for_permission(permission) -> object | None:
    """Return the constraint checker instance for a policy permission, if any."""
    if permission.constraints is None:
        return None
    from intentframe_action_bundle.manifest import constraint_checkers

    return constraint_checkers().get(type(permission.constraints))


def action_metadata(action_id: str) -> dict:
    """Summarize routing metadata for an action (manifest + policy-agnostic tags)."""
    manifest = manifest_for(action_id)
    if manifest is None:
        return {"action_id": action_id, "bundle_id": None}
    return {
        "action_id": action_id,
        "bundle_id": manifest.bundle_id,
        "passive_read": manifest.passive_read or action_id in manifest.action_ids,
        "critical": manifest.critical,
        "ae_prompt_ids": sorted(manifest.ae_prompt_ids),
        "has_pre_pipeline": manifest.has_pre_pipeline,
        "has_executor_floor": manifest.has_executor_floor,
        "constraint_type": (
            manifest.constraint_type.__name__ if manifest.constraint_type else None
        ),
    }
