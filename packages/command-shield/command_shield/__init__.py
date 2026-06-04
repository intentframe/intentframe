"""command_shield — deterministic shell command & code inspection.

Standalone module.  No imports from intentframe_components,
policy_registry, or executor.  Used by the IntentFrame runtime as a
pre-execution gate and by ad-hoc tooling that needs structured
findings on a shell command or a raw code body.

Model
-----
A shell command is the root of a graph of code units linked by
*containment edges*::

    inline       python -c "import os; os.system(...)"
    referenced   python foo.py                      (resolvable path)
    piped_stdin  cat foo.py | python -
    dynamic      python $SCRIPT  /  python <(curl ...)
    interactive  bash                               (no body)

The pipeline walks this graph: cheap → expensive checks, emits
structured signals for each finding, and — when the caller opts in —
auto-resolves local referenced scripts, sniffs their language from
content, and delegates each body to :func:`inspect_code`.

Verdict (CATASTROPHIC / NEEDS_REVIEW / SAFE) is set ONLY by
fixed-system checks (pattern and structural).  Every other signal is
advisory context for the caller.

Public API
----------
inspect_command(cmd, *, session=None, config=None) -> CommandReport
    Sync command inspection.  No LLM, no network.  Runtime gate.

inspect_command_deep(cmd, *, ...) -> CommandReport  (async)
    Same, plus conditional LLM review of the first in-scope body.

inspect_code(code, *, language=None, source_path=None, config=None)
    Sync code-only inspector.  Use when you already have the body.

inspect_code_deep(code, *, ...) -> CodeReport  (async)
    Code-only inspector with conditional LLM review.

quick_check(cmd, *, config=None) -> CommandReport
    Executor last-resort floor (patterns only; no structural walk).

clean_env() -> dict[str, str]
    Filtered ``os.environ`` safe to pass into child processes.

Types
-----
Verdict, Signal, CommandReport, CodeReport, ResolvedNode, Edge,
ShieldConfig, ResolveSession.
"""

from command_shield.code_inspector import inspect_code, inspect_code_deep
from command_shield.config import DEFAULT_CONFIG, ShieldConfig
from command_shield.env import clean_env
from command_shield.pipeline import inspect_command, inspect_command_deep
from command_shield.quick import quick_check
from command_shield.resolve import ResolveSession
from command_shield.verdict import (
    CodeReport,
    CommandReport,
    Edge,
    ResolvedNode,
    Signal,
    Verdict,
)

__all__ = [
    "DEFAULT_CONFIG",
    "CodeReport",
    "CommandReport",
    "Edge",
    "ResolveSession",
    "ResolvedNode",
    "ShieldConfig",
    "Signal",
    "Verdict",
    "clean_env",
    "inspect_code",
    "inspect_code_deep",
    "inspect_command",
    "inspect_command_deep",
    "quick_check",
]
