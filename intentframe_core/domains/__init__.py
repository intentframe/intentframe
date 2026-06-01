"""Domain schema base type for ``IntentFrame.data`` slices.

Concrete domain intent schemas (finance, deletion, …) live in
``action_registry.domains``. This package only provides the shared
``DomainSchema`` base so ``intentframe_core`` stays free of registry imports.
"""

from intentframe_core.domains.base import DomainSchema

__all__ = ["DomainSchema"]
