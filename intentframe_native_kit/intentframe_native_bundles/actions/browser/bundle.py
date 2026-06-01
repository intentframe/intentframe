"""Browser action bundle."""

from __future__ import annotations

import fnmatch

from intentframe_native_kit.action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_native_kit.intentframe_native_bundles.actions.browser.constraints import BrowserConstraints
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleContext,
    BundlePhaseOutcome,
)


class BrowserActionBundle(ActionBundle):
    bundle_id = "browser"
    action_ids = frozenset({
        ActionType.GET_PAGE_CONTENT.value,
        ActionType.OPEN_URL.value,
    })
    passive_read_action_ids = frozenset({ActionType.GET_PAGE_CONTENT.value})

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            BrowserConstraints.model_validate(action_permission.constraints)

    async def enforce_constraints(
        self,
        intent: IntentFrame,
        action_permission: ActionPermission,
        ctx: BundleContext,
        *,
        verbose: bool = False,
    ) -> BundlePhaseOutcome:
        del verbose
        if action_permission.constraints is None:
            return BundlePhaseOutcome.continue_(ctx)
        constraints = BrowserConstraints.model_validate(action_permission.constraints)
        url = (intent.data or {}).get("url")
        if url is None or (isinstance(url, str) and not url.strip()):
            return BundlePhaseOutcome.block(
                ctx,
                reason=(
                    "Constraint violation: URL is required to evaluate "
                    "allowed_urls policy"
                ),
                matched_gate="constraint",
            )
        for pattern in constraints.allowed_urls:
            if fnmatch.fnmatch(url, pattern):
                return BundlePhaseOutcome.continue_(ctx)
        return BundlePhaseOutcome.block(
            ctx,
            reason=f"Constraint violation: URL '{url}' not in allowed URLs",
            matched_gate="constraint",
        )

    async def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = BrowserConstraints.model_validate(action_permission.constraints)
        return f"Allowed URLs: {', '.join(constraints.allowed_urls)}"
