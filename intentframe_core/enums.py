"""
Enums for IntentFrame System

IntentFrame-specific enumerations.
ActionType lives in the action_registry module (universal taxonomy).
"""

from enum import Enum

from action_registry import ActionType  # re-export for backward compat

__all__ = ["ActionType", "Decision", "Reversibility", "RiskLevel"]


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
