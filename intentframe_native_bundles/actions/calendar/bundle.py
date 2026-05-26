"""Calendar action bundle."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.types import IntentFrame

from intentframe_native_bundles.actions.calendar.constraints import CalendarConstraints
from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.types import (
    ActionPermission,
    BundleContext,
    BundlePhaseOutcome,
)

_CALENDAR_READ_ACTIONS = frozenset({
    ActionType.LIST_CALENDARS.value,
    ActionType.LIST_EVENTS.value,
    ActionType.SEARCH_EVENTS.value,
})

_CALENDAR_WRITE_ACTIONS = frozenset({
    ActionType.CREATE_EVENT.value,
    ActionType.UPDATE_EVENT.value,
    ActionType.DELETE_EVENT.value,
})


class CalendarActionBundle(ActionBundle):
    bundle_id = "calendar"
    action_ids = _CALENDAR_READ_ACTIONS | _CALENDAR_WRITE_ACTIONS
    passive_read_action_ids = _CALENDAR_READ_ACTIONS

    def validate_constraints(self, action_permission: ActionPermission) -> None:
        if action_permission.constraints is not None:
            CalendarConstraints.model_validate(action_permission.constraints)

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
        constraints = CalendarConstraints.model_validate(action_permission.constraints)
        if constraints.allowed_calendars is not None:
            calendar = (intent.data or {}).get("calendar") or intent.target
            if calendar not in constraints.allowed_calendars:
                return BundlePhaseOutcome.block(
                    ctx,
                    reason=(
                        f"Constraint violation: Calendar '{calendar}' "
                        "not in allowed calendars"
                    ),
                    matched_gate="constraint",
                )
        return BundlePhaseOutcome.continue_(ctx)

    async def describe_constraints(self, action_permission: ActionPermission) -> str | None:
        if action_permission.constraints is None:
            return None
        constraints = CalendarConstraints.model_validate(action_permission.constraints)
        if constraints.allowed_calendars is not None:
            return f"Allowed calendars: {', '.join(constraints.allowed_calendars)}"
        return "Calendar constraints configured"
