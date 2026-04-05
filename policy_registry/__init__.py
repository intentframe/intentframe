"""
Policy Registry -- device-level policy store.

The registry is a *data store* for user-configured policies on their device.
It is self-contained and independent of IntentFrame or any other consumer.
Consumers read from it and apply their own logic.

Usage:
    from policy_registry import PolicyRegistry, UserPolicy, ActionPermission
    from policy_registry.constraints import FileConstraints

    registry = PolicyRegistry()
    registry.set_user_policy(UserPolicy(
        user_id="finance_001",
        allowed_actions={
            "READ_FILE": ActionPermission(
                safe=True,
                constraints=FileConstraints(allowed_paths=["/invoices/"]),
            ),
        },
    ))
"""

from policy_registry.models import ActionPermission, SemanticIntentLimit, UserPolicy
from policy_registry.registry import PolicyRegistry

__all__ = [
    "ActionPermission",
    "PolicyRegistry",
    "SemanticIntentLimit",
    "UserPolicy",
]
