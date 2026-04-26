"""Helpers for DG accuracy tests.

Core contract: tests here never hand-construct ``CommandIntel``.  Every
decision is driven by running the real :func:`command_shield.inspect_command`
on the raw command string and building ``CommandIntel`` the same way
:mod:`intentframe_server.pipeline` does — so the classifier and DG are
exercised as a pair.

That way a classifier miss (wrong verdict, missing capability tag,
missed edge signal) surfaces here as a DG decision drift, not a silent
pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from action_registry.types import ActionType
from command_shield import Verdict, inspect_command
from intentframe_components.guardian.deterministic import (
    DeterministicGuardian,
    DeterministicResult,
)
from intentframe_core.types import CommandIntel, IntentFrame, UserContext


@dataclass(frozen=True)
class ShieldView:
    """What command_shield saw — kept around so tests can assert on the
    classifier's own output, not just DG's downstream decision."""

    verdict: str
    capabilities: tuple[str, ...]
    has_edge_signals: bool
    has_code_intel_findings: bool
    finding_ids: tuple[str, ...]


def build_shield_view(command: str) -> ShieldView:
    """Run the real inspect_command and summarize the way pipeline.py does."""
    report = inspect_command(command)

    code_intel = report.code_intel
    finding_ids: tuple[str, ...] = ()
    if code_intel is not None and code_intel.findings:
        finding_ids = tuple(
            getattr(f, "finding_id", "") for f in code_intel.findings
        )

    has_edge_signals = any(
        s.check == "edge" or s.signal_id.startswith("edge:")
        for s in report.signals
    )

    return ShieldView(
        verdict=report.verdict.value,
        capabilities=tuple(report.capabilities),
        has_edge_signals=has_edge_signals,
        has_code_intel_findings=bool(finding_ids),
        finding_ids=finding_ids,
    )


def build_command_intel(command: str) -> tuple[CommandIntel | None, ShieldView]:
    """Build CommandIntel from the real classifier.

    Returns ``(None, view)`` for CATASTROPHIC verdicts — the pipeline
    would short-circuit at command_shield and DG would never see this
    command.  Tests that focus on DG should skip those; the full-pipeline
    catastrophic behavior is covered elsewhere.
    """
    view = build_shield_view(command)
    if view.verdict == Verdict.CATASTROPHIC.value:
        return None, view

    intel = CommandIntel(
        verdict=view.verdict,
        capabilities=view.capabilities,
        has_code_intel_findings=view.has_code_intel_findings,
        code_intel_finding_ids=view.finding_ids,
        has_edge_signals=view.has_edge_signals,
    )
    return intel, view


def run_dg(
    command: str,
    user_context: UserContext,
    dg: DeterministicGuardian | None = None,
) -> tuple[DeterministicResult, ShieldView]:
    """Drive DG for a RUN_COMMAND with real classifier output.

    ``dg`` is optional so callers can share a single instance across a
    parametrized run; a fresh one is created per call by default to
    keep tests independent.
    """
    intel, view = build_command_intel(command)
    dg = dg or DeterministicGuardian()
    intent = IntentFrame(
        action=ActionType.RUN_COMMAND,
        target=command,
        data=None,
        reason="accuracy test",
        agent_id="dg_accuracy",
    )
    result = dg.decide(intent, user_context, command_intel=intel)
    return result, view
