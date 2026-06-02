"""
Action Catalog — the device-level registry of available actions.

Stores ActionMeta entries and answers queries.
This is a data store with lookup methods — no policy logic.

At startup, the universal actions are registered automatically.
Platform modules (e.g. platforms/macos/) register additional actions.
Consumer apps can register their own action types.
"""

from __future__ import annotations

import logging
from typing import Optional

from intentframe_native_kit.action_registry.types import (
    ACTION_CATEGORIES,
    ActionCategory,
    ActionMeta,
    ActionType,
)

logger = logging.getLogger(__name__)


class ActionCatalog:
    """Device-level catalog of available action types.

    Usage:
        catalog = ActionCatalog()
        catalog.register_defaults()        # universal actions
        register_macos_actions(catalog)     # platform-specific

        meta = catalog.get("READ_FILE")
        file_actions = catalog.get_by_category(ActionCategory.FILE)
    """

    def __init__(self) -> None:
        self._actions: dict[str, ActionMeta] = {}

    def register(
        self,
        action_type: str,
        category: ActionCategory,
        *,
        description: str = "",
        platform: str = "universal",
        reversible: bool = False,
    ) -> None:
        """Register an action type into the catalog.

        Raises ValueError if the action is already registered
        to a different category (catches config errors at startup).
        """
        existing = self._actions.get(action_type)
        if existing is not None and existing.category != category:
            raise ValueError(
                f"Action '{action_type}' already registered under "
                f"'{existing.category.value}', cannot re-register "
                f"under '{category.value}'."
            )

        self._actions[action_type] = ActionMeta(
            action_type=action_type,
            category=category,
            description=description,
            platform=platform,
            reversible=reversible,
        )

    def register_defaults(self) -> None:
        """Register all universal action types from the canonical mapping."""
        for action_type, category in ACTION_CATEGORIES.items():
            self.register(
                action_type=action_type.value,
                category=category,
                platform="universal",
            )
        logger.info("Registered %d universal actions", len(ACTION_CATEGORIES))

    def get(self, action_type: str) -> Optional[ActionMeta]:
        """Look up metadata for an action type. Returns None if not found."""
        return self._actions.get(action_type)

    def is_registered(self, action_type: str) -> bool:
        return action_type in self._actions

    def get_by_category(self, category: ActionCategory) -> list[ActionMeta]:
        return [m for m in self._actions.values() if m.category == category]

    def get_by_platform(self, platform: str) -> list[ActionMeta]:
        return [m for m in self._actions.values() if m.platform == platform]

    def all_actions(self) -> list[ActionMeta]:
        return list(self._actions.values())

    def all_action_types(self) -> list[str]:
        return sorted(self._actions.keys())

    def __contains__(self, action_type: str) -> bool:
        return action_type in self._actions

    def __len__(self) -> int:
        return len(self._actions)
