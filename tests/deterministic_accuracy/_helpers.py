"""Helpers for DG accuracy tests — full Bundle SDK lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import patch

from intentframe_native_kit.action_registry.types import ActionType
from command_shield import Verdict, inspect_command
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_bundle_sdk.types import BundlePhaseOutcome
from intentframe_components.guardian.deterministic import (
    DeterministicGuardian,
    DeterministicResult,
)
from intentframe_core.types import IntentFrame, UserContext


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


async def decide_dg(
    dg: DeterministicGuardian,
    intent: IntentFrame,
    user_context: UserContext,
) -> DeterministicResult:
    """Await production DG API (tests only)."""
    return await dg.decide_async(intent, user_context)


def decide_dg_sync(
    dg: DeterministicGuardian,
    intent: IntentFrame,
    user_context: UserContext,
) -> DeterministicResult:
    """Sync wrapper for pytest without a running loop."""
    return asyncio.run(decide_dg(dg, intent, user_context))


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
        data={"command": command},
        reason="accuracy test",
        agent_id="dg_accuracy",
    )
    result = decide_dg_sync(dg, intent, user_context)
    return result, view


def run_dg_with_intel(
    command: str,
    user_context: UserContext,
    command_intel: CommandIntel,
    dg: DeterministicGuardian | None = None,
) -> DeterministicResult:
    """Pin checker gates with seeded command_intel (skips real shield)."""

    from intentframe_native_kit.intentframe_native_bundles.actions.terminal.evidence import COMMAND_INTEL_KEY

    async def seed_prepare(self, intent, ctx, *, verbose=False):
        del intent, verbose
        ctx.evidence[COMMAND_INTEL_KEY] = command_intel
        return BundlePhaseOutcome.continue_(ctx)

    dg = dg or DeterministicGuardian()
    with patch.object(TerminalActionBundle, "prepare_evidence", seed_prepare):
        result, _ = run_dg(command, user_context, dg)
    return result
