"""Verdict model for command_shield.

Three verdicts, no command modification — classification only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    CATASTROPHIC = "CATASTROPHIC"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SAFE = "SAFE"


@dataclass(frozen=True)
class Signal:
    """A single finding from one of the analysis checks."""

    check: str  # "pattern", "structural", "indirection", "shellcheck"
    signal_id: str  # e.g. "MAC-DISK-001", "command-substitution"
    description: str
    evidence: str  # matched substring or AST node repr


@dataclass(frozen=True)
class CommandReport:
    """Immutable analysis result for a single command."""

    verdict: Verdict
    command: str
    normalized_command: str
    signals: tuple[Signal, ...] = ()
    sub_commands: tuple[str, ...] = ()

    @property
    def is_catastrophic(self) -> bool:
        return self.verdict is Verdict.CATASTROPHIC

    @property
    def needs_review(self) -> bool:
        return self.verdict is Verdict.NEEDS_REVIEW
