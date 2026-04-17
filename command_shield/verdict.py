"""Verdict model for command_shield.

Three verdicts, no command modification — classification only.

The verdict is 3-way (CATASTROPHIC / NEEDS_REVIEW / SAFE) and is set
only by fixed-system checks (pattern matches + structural evasion).
Config-driven signals (COMMAND_TOO_LARGE, OUT_OF_SCOPE, CODE_TOO_LARGE,
capability:*) ride in `signals` with severity but never change the
verdict.  Guardian decides what to do with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from command_shield.review.types import CodeIntel, LanguageInfo, ReviewFinding


class Verdict(Enum):
    CATASTROPHIC = "CATASTROPHIC"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SAFE = "SAFE"


@dataclass(frozen=True)
class Signal:
    """A single finding from one of the analysis checks."""

    check: str  # "pattern", "structural", "indirection", "shellcheck", "capability", "scope", "size"
    signal_id: str  # e.g. "MAC-DISK-001", "command-substitution", "capability:package_install"
    description: str
    evidence: str  # matched substring or AST node repr
    severity: str = "info"  # "critical", "high", "medium", "low", "info"


@dataclass(frozen=True)
class CommandReport:
    """Immutable analysis result for a single command.

    Core fields (always populated) carry the 3-way verdict and the raw
    signal list — this is the minimum contract the pipeline, AE, and
    executor consume.

    Extended fields (populated as later steps run) carry language,
    capability, code-intel, and LLM-review context.  They default to
    empty so any caller reading just `verdict` + `signals` keeps
    working unchanged.
    """

    # ── Core (stable contract) ────────────────────────────────────
    verdict: Verdict
    command: str
    normalized_command: str
    signals: tuple[Signal, ...] = ()
    sub_commands: tuple[str, ...] = ()

    # ── Extended (populated as pipeline progresses) ───────────────
    language: "LanguageInfo | None" = None
    capabilities: tuple[str, ...] = ()
    code_intel: "CodeIntel | None" = None
    reviewer_findings: tuple["ReviewFinding", ...] = field(default_factory=tuple)
    reviewer_summary: str = ""
    reviewer_ran: bool = False
    elapsed_ms: float = 0.0

    @property
    def is_catastrophic(self) -> bool:
        return self.verdict is Verdict.CATASTROPHIC

    @property
    def needs_review(self) -> bool:
        return self.verdict is Verdict.NEEDS_REVIEW
