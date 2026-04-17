"""Examination types for command_shield.review.

Standalone — no imports from intentframe_components, policy_registry,
or executor.  These types carry examination findings; the consumer
(IntentFrame or any other caller) decides what to do with them.
"""

from __future__ import annotations

from dataclasses import dataclass

from command_shield.verdict import CommandReport


@dataclass(frozen=True)
class ReviewFinding:
    """A single finding from any examination step."""

    source: str        # "pattern", "structural", "code_intel", "reviewer"
    finding_id: str    # e.g. "DANGEROUS_IMPORT_subprocess", "EVAL_CALL"
    severity: str      # "critical", "high", "medium", "low", "info"
    title: str
    detail: str
    evidence: str
    confidence: float  # 0.0–1.0


@dataclass(frozen=True)
class LanguageInfo:
    """Detected language / interpreter for a command."""

    language: str | None     # "python", "shell", "javascript", "unknown"
    interpreter: str | None  # basename of the interpreter, e.g. "python3"
    is_inline: bool          # True for -c / -e / --eval style inline code
    is_file_exec: bool       # True for `python script.py` style


@dataclass(frozen=True)
class CodeIntel:
    """Static-analysis results for code content (Python or shell)."""

    language: str | None
    file_path: str | None
    imports: tuple[str, ...]
    dangerous_calls: tuple[str, ...]
    findings: tuple[ReviewFinding, ...]


@dataclass(frozen=True)
class CommandReview:
    """Complete examination output from command_shield.review.

    Pure analysis — no policy decisions.  The caller reads this and
    applies its own allow/block logic on top.
    """

    command_report: CommandReport
    language_info: LanguageInfo | None
    code_intel: CodeIntel | None
    reviewer_findings: tuple[ReviewFinding, ...]
    reviewer_summary: str
    reviewer_ran: bool
    all_findings: tuple[ReviewFinding, ...]
    elapsed_ms: float
