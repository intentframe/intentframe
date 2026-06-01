"""
Enums for IntentFrame System

IntentFrame-specific enumerations.

The action taxonomy (``ActionType``) deliberately lives in ``action_registry``,
not here. ``intentframe_core`` is a neutral, lower-level layer and must not
depend on the registry; ``IntentFrame.action`` is a plain string.
"""

from enum import Enum

__all__ = ["Decision", "Reversibility", "RiskLevel"]


class Decision(Enum):
    """Guardian's possible decisions — binary, no middle ground."""
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class Reversibility(Enum):
    """How reversible is an action?"""
    FULLY_REVERSIBLE = "FULLY_REVERSIBLE"
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
    TIME_LIMITED = "TIME_LIMITED"
    IRREVERSIBLE = "IRREVERSIBLE"
    UNKNOWN = "UNKNOWN"


class RiskLevel(Enum):
    """Risk assessment levels"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
