"""command_shield — deterministic shell command classification.

Classifies commands as CATASTROPHIC, NEEDS_REVIEW, or SAFE before
they enter the IntentFrame pipeline.  Standalone module with no
imports from intentframe_components, policy_registry, or executor.

Public API
----------
analyze(command)    Full pipeline (runtime pre-pipeline).
quick_check(command) Fast subset (executor last-resort floor).
clean_env()         Filtered os.environ for subprocess execution.
Verdict             Enum: CATASTROPHIC | NEEDS_REVIEW | SAFE.
CommandReport       Frozen dataclass with verdict + signals.
Signal              Single finding from an analysis check.
"""

from command_shield.analyzer import analyze
from command_shield.env import clean_env
from command_shield.quick import quick_check
from command_shield.verdict import CommandReport, Signal, Verdict

__all__ = [
    "CommandReport",
    "Signal",
    "Verdict",
    "analyze",
    "clean_env",
    "quick_check",
]
