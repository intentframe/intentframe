"""
Action Registry — universal action taxonomy for the device.

Defines what actions CAN exist.  No constraints, no policies.
Both the Policy Registry and IntentFrame import from here.

Usage:
    from action_registry import ActionType, ActionCategory, ActionCatalog

    catalog = ActionCatalog()
    catalog.register_defaults()
"""

from action_registry.types import (
    ACTION_CATEGORIES,
    ACTION_DOMAINS,
    ActionCategory,
    ActionMeta,
    ActionType,
    DomainType,
    get_category,
    get_domain,
)
from action_registry.catalog import ActionCatalog

__all__ = [
    "ACTION_CATEGORIES",
    "ACTION_DOMAINS",
    "ActionCatalog",
    "ActionCategory",
    "ActionMeta",
    "ActionType",
    "DomainType",
    "get_category",
    "get_domain",
]
