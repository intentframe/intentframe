"""
Action dispatcher -- routes action types to capability adapters.

The dispatcher maintains a registry of action_type -> CapabilityAdapter
mappings. When the gateway receives an ExecutionRequest, it asks the
dispatcher to resolve the action_type to the correct adapter.

Design:
    - Simple dict-based dispatch. No magic, no reflection.
    - Each action type maps to exactly ONE adapter.
    - Action types must be globally unique across all registered adapters.
    - Unknown action types cause immediate rejection (fail-closed).
    - Adapters register their supported actions at startup.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from executor.adapters.base import CapabilityAdapter
from executor.exceptions import AdapterNotFoundError

if TYPE_CHECKING:
    from action_registry.catalog import ActionCatalog

logger = logging.getLogger(__name__)

__all__ = ["ActionDispatcher"]


class ActionDispatcher:
    """Routes action types to their registered capability adapters.

    Optionally accepts an ActionCatalog for startup validation:
    every action an adapter claims to handle must be registered in the
    universal catalog.  This catches typos and drift at startup.

    Usage:
        from action_registry import ActionCatalog

        catalog = ActionCatalog()
        catalog.register_defaults()

        dispatcher = ActionDispatcher(catalog=catalog)
        dispatcher.register(mail_adapter)
        dispatcher.register(files_adapter)

        adapter = dispatcher.resolve("SEND_EMAIL")
    """

    def __init__(self, catalog: ActionCatalog | None = None) -> None:
        self._action_to_adapter: dict[str, CapabilityAdapter] = {}
        self._adapter_registry: dict[str, CapabilityAdapter] = {}
        self._catalog = catalog

    def register(self, adapter: CapabilityAdapter) -> None:
        """Register an adapter and all its supported actions.

        Each action type in adapter.supported_actions() is mapped to
        this adapter. Duplicate action types raise ValueError to catch
        configuration errors at startup (not at runtime).

        If an ActionCatalog was provided, every action is validated
        against it — unrecognized actions trigger a warning (not a
        hard error, since platform-specific actions may not yet be in
        the catalog).

        Args:
            adapter: The adapter instance to register.

        Raises:
            ValueError: If any action type is already registered
                        to a different adapter.
        """
        manifest = adapter.manifest()
        adapter_id = manifest.adapter_id

        for action in adapter.supported_actions():
            # Catalog validation (warn on unknown)
            if self._catalog is not None and not self._catalog.is_registered(action):
                logger.warning(
                    "Adapter '%s' supports action '%s' which is not in "
                    "the ActionCatalog. Register it or check for typos.",
                    adapter_id,
                    action,
                )

            existing = self._action_to_adapter.get(action)
            if existing is not None:
                existing_id = existing.manifest().adapter_id
                if existing_id != adapter_id:
                    raise ValueError(
                        f"Action '{action}' is already registered to adapter "
                        f"'{existing_id}'. Cannot register to '{adapter_id}'. "
                        f"Each action type must map to exactly one adapter."
                    )

            self._action_to_adapter[action] = adapter

        self._adapter_registry[adapter_id] = adapter

        logger.info(
            "Registered adapter: id=%s actions=%s",
            adapter_id,
            adapter.supported_actions(),
        )

    def resolve(self, action_type: str) -> CapabilityAdapter:
        """Resolve an action type to its registered adapter.

        Args:
            action_type: The action to look up (e.g., "SEND_EMAIL").

        Returns:
            The CapabilityAdapter registered for this action.

        Raises:
            AdapterNotFoundError: If no adapter handles this action type.
        """
        adapter = self._action_to_adapter.get(action_type)
        if adapter is None:
            registered = ", ".join(sorted(self._action_to_adapter)) or "(none)"
            raise AdapterNotFoundError(
                f"No adapter registered for action: '{action_type}'. "
                f"Registered actions: {registered}",
            )
        return adapter

    def get_adapter(self, adapter_id: str) -> CapabilityAdapter | None:
        """Look up an adapter by its ID. Returns None if not found."""
        return self._adapter_registry.get(adapter_id)

    @property
    def registered_actions(self) -> list[str]:
        """All action types that have a registered adapter."""
        return sorted(self._action_to_adapter.keys())

    @property
    def registered_adapters(self) -> list[str]:
        """All registered adapter IDs."""
        return sorted(self._adapter_registry.keys())

    def __contains__(self, action_type: str) -> bool:
        """Check if an action type is registered."""
        return action_type in self._action_to_adapter

    def __len__(self) -> int:
        """Number of registered action types."""
        return len(self._action_to_adapter)
