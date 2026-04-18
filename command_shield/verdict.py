"""Verdict model for command_shield.

Three verdicts, no command modification — classification only.

The verdict is 3-way (CATASTROPHIC / NEEDS_REVIEW / SAFE) and is set
only by fixed-system checks (pattern matches + structural evasion).
Config-driven signals (COMMAND_TOO_LARGE, OUT_OF_SCOPE, CODE_TOO_LARGE,
capability:*, edge:*, resolved:*) ride in `signals` with severity but
never change the verdict.  Guardian decides what to do with them.
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

    check: str
    """One of:
        "pattern", "structural", "indirection", "shellcheck",
        "capability", "scope", "size", "edge", "resolvability",
        "resolved".
    """

    signal_id: str  # e.g. "MAC-DISK-001", "command-substitution", "edge:referenced"
    description: str
    evidence: str  # matched substring or AST node repr
    severity: str = "info"  # "critical", "high", "medium", "low", "info"


# ── Containment edges (graph of code units the command may execute) ──


@dataclass(frozen=True)
class Edge:
    """One outgoing containment edge from a command to another code body.

    A command is a *shell* code unit; each edge describes a different
    inner code unit the command may cause to execute:

        inline       Body is in-band in the command (e.g. `python -c "..."`).
        referenced   Body is at a file path referenced by the command
                     (e.g. `python foo.py`, `source .env`).
        piped_stdin  Body is streamed from another process into an
                     interpreter (e.g. `cat foo.py | python -`).
        dynamic      Path is produced at shell-eval time and cannot be
                     resolved statically (variable expansion, command
                     substitution, glob, process substitution).
        interactive  Interpreter invoked without a body — REPL / stdin.
        compiled     Referenced file is a compiled artefact — no source.

    `resolvable` is True only for edges whose inner body can be
    obtained deterministically before execution (inline always,
    referenced when the path is a literal, compiled never).
    """

    kind: str  # see docstring
    language: str | None = None
    body: str | None = None
    path_arg: str | None = None
    resolvable: bool = False
    unresolvable_reason: str | None = None
    position: tuple[int, int] = (0, 0)
    sub_kind: str | None = None  # e.g. "read-not-exec", "source"
    depth: int = 0               # 0 = outermost command, 1 = first indirection, ...


@dataclass(frozen=True)
class CodeReport:
    """Analysis result for a raw code body (file content or snippet).

    Produced by :func:`command_shield.code_inspector.inspect_code` and
    also embedded in :class:`ResolvedNode` when a command pipeline
    resolves a file.  Pure code-level facts — no shell semantics, no
    policy decisions.
    """

    language: str | None
    source_path: str | None
    code_intel: "CodeIntel | None" = None
    signals: tuple[Signal, ...] = ()
    reviewer_findings: tuple["ReviewFinding", ...] = field(default_factory=tuple)
    reviewer_summary: str = ""
    reviewer_ran: bool = False
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class ResolvedNode:
    """A resolved containment edge together with its code-level report.

    `code_report` is populated when resolution succeeded AND the file
    was in scope for analysis.  When skipped (unresolvable,
    out-of-scope language, oversized, disabled by config), only
    `edge` and `skipped_reason` are meaningful.
    """

    edge: Edge
    path: str | None = None
    language: str | None = None
    code_report: CodeReport | None = None
    skipped_reason: str | None = None


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

    Graph-model fields (`edges`, `resolved_nodes`,
    `script_path_candidate`, `script_resolved`) expose the containment
    graph the pipeline discovered and — when `auto_resolve_local` is
    on — walked.  `code_intel` mirrors the most informative resolved
    node so simple consumers can read one accessor for the primary
    code-level facts.
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

    # ── Graph model (edges + resolved children) ───────────────────
    edges: tuple[Edge, ...] = ()
    resolved_nodes: tuple[ResolvedNode, ...] = ()
    script_path_candidate: str | None = None
    script_resolved: bool = False

    @property
    def is_catastrophic(self) -> bool:
        return self.verdict is Verdict.CATASTROPHIC

    @property
    def needs_review(self) -> bool:
        return self.verdict is Verdict.NEEDS_REVIEW
