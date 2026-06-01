"""
Action Registry — universal action taxonomy for the device.

Defines what actions CAN exist. No constraints, no policies — just the
shared vocabulary (``ActionType``, ``ActionCategory``, ``DomainType``,
``ACTION_DOMAINS``, …).

Layering:
    - ``intentframe_core`` — neutral DTOs; ``IntentFrame.action`` is a plain
      string and must not import this package.
    - ``intentframe_native_kit.action_registry`` (this package) — taxonomy + domain intent schemas
      in ``intentframe_native_kit.action_registry.domains``; may import ``intentframe_core``.
    - Agent authors (Jarvis, third-party agents) — optional local imports for
      fail-fast validation before ``Actor.submit()``.
    - Bundles / executor — enforce policy and dispatch using string action ids.

Domain schemas are **not** re-exported from this ``__init__`` (import
``intentframe_native_kit.action_registry.domains`` directly) to avoid a circular import through
``intentframe_core.enums`` at package load time.

Usage::

    from intentframe_native_kit.action_registry import ActionType, ActionCatalog
    from intentframe_native_kit.action_registry.domains import DOMAIN_SCHEMAS, DeletionIntentData

    catalog = ActionCatalog()
    catalog.register_defaults()
"""

from intentframe_native_kit.action_registry.types import (
    ACTION_CATEGORIES,
    ACTION_DOMAINS,
    ActionCategory,
    ActionMeta,
    ActionType,
    DomainType,
    get_category,
    get_domain,
)
from intentframe_native_kit.action_registry.catalog import ActionCatalog

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
