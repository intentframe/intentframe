"""Internal analyser types shared by code_intel and the LLM reviewer.

These are implementation details — the public surface lives at the
top of the package.  Callers that consume inspection output read
:class:`command_shield.CodeReport` / :class:`command_shield.CommandReport`,
which in turn embed these.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewFinding:
    """A single structured finding from a code analyser."""

    source: str       # "code_intel" | "reviewer"
    finding_id: str   # e.g. "DANGEROUS_IMPORT_subprocess"
    severity: str     # "critical" | "high" | "medium" | "low" | "info"
    title: str
    detail: str
    evidence: str
    confidence: float  # 0.0–1.0


@dataclass(frozen=True)
class LanguageInfo:
    """Detected language / interpreter for a command string."""

    language: str | None     # "python", "shell", "javascript", "unknown"
    interpreter: str | None  # basename, e.g. "python3"
    is_inline: bool          # True for -c / -e / --eval style inline code
    is_file_exec: bool       # True for `python script.py` style


@dataclass(frozen=True)
class CodeIntel:
    """Static-analysis results for one code body (Python or shell)."""

    language: str | None
    file_path: str | None
    imports: tuple[str, ...]
    dangerous_calls: tuple[str, ...]
    findings: tuple[ReviewFinding, ...]
