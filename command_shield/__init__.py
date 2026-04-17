"""command_shield — deterministic shell command classification.

Classifies commands as CATASTROPHIC, NEEDS_REVIEW, or SAFE before
they enter the IntentFrame pipeline.  Standalone module with no
imports from intentframe_components, policy_registry, or executor.

Architecture
------------
All inspection flows through a single 12-step pipeline
(:mod:`command_shield.pipeline`):

    1  length check                  7  capability classify
    2  normalize + tokenize           8  code extraction
    3  pattern match (verdict)        9  code length check
    4  structural decompose           10 deterministic code analysis
    5  language detect                11 LLM reviewer (async only)
    6  scope check                    12 assemble CommandReport

The 3-way verdict is driven only by fixed-system checks (steps 3 & 4).
Config-driven signals (size, scope, capabilities) ride with severity
but never change the verdict.  Guardian/AE decide what to do with them.

Public API
----------
inspect_command(cmd, *, config=...)        Sync pipeline (steps 1-10, 12).
inspect_command_deep(cmd, *, config=...)   Async pipeline (steps 1-12).
quick_check(cmd, *, config=...)            Executor last-resort floor.
analyze(cmd, *, ...)                       Back-compat alias for inspect_command.
review_command(cmd, ...)                   Back-compat adapter returning CommandReview.
clean_env()                                Filtered os.environ for subprocess.

Types
-----
Verdict, Signal, CommandReport                        core
ShieldConfig                                          operational config
LanguageInfo, CodeIntel, ReviewFinding, CommandReview review extensions
"""

from command_shield.analyzer import analyze
from command_shield.config import DEFAULT_CONFIG, ShieldConfig
from command_shield.env import clean_env
from command_shield.pipeline import inspect_command, inspect_command_deep
from command_shield.quick import quick_check
from command_shield.review import review_command
from command_shield.review.types import (
    CodeIntel,
    CommandReview,
    LanguageInfo,
    ReviewFinding,
)
from command_shield.verdict import CommandReport, Signal, Verdict

__all__ = [
    "DEFAULT_CONFIG",
    "CodeIntel",
    "CommandReport",
    "CommandReview",
    "LanguageInfo",
    "ReviewFinding",
    "ShieldConfig",
    "Signal",
    "Verdict",
    "analyze",
    "clean_env",
    "inspect_command",
    "inspect_command_deep",
    "quick_check",
    "review_command",
]
