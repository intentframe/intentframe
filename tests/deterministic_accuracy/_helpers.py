"""Helpers for DG accuracy tests.

Exercises the full Bundle SDK lifecycle: permission → prepare_evidence →
enrich → check_policy → domain → structural_gates → allow_gates.
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
    """What command_shield saw — kept for test assertions."""

    verdict: str
    capabilities: tuple[str, ...]
    has_edge_signals: bool
    has_code_intel_findings: bool
    finding_ids: tuple[str, ...]


def build_shield_view(command: str) -> ShieldView:
    """Run the real inspect_command and summarize."""
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
    """Build CommandIntel from classifier (None when CATASTROPHIC)."""
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
    """Drive full DG lifecycle for RUN_COMMAND with real command_shield."""
    view = build_shield_view(command)
    dg = dg or DeterministicGuardian()
    intent = IntentFrame(
        action=ActionType.RUN_COMMAND,
        target=command,
        data=None,
        reason="accuracy test",
        agent_id="dg_accuracy",
    )
    result = dg.decide(intent, user_context, command_intel=None)
    return result, view


def run_dg_with_intel(
    command: str,
    user_context: UserContext,
    command_intel,
    dg: DeterministicGuardian | None = None,
) -> DeterministicResult:
    """Drive DG check_policy + gates only (skip evidence/enrich) — for gate-order pins."""
    dg = dg or DeterministicGuardian()
    intent = IntentFrame(
        action=ActionType.RUN_COMMAND,
        target=command,
        data=None,
        reason="accuracy test",
        agent_id="dg_accuracy",
    )
    return dg.decide(intent, user_context, command_intel=command_intel)
