"""RUN_COMMAND pre-pipeline — command_shield + CommandIntel."""

from __future__ import annotations

from typing import Any

from command_shield import Verdict, inspect_command as shield_inspect
from intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_core.types import ExecutionResult, IntentFrame


def run_terminal_pre_pipeline(
    intent: IntentFrame,
    *,
    verbose: bool = False,
) -> tuple[
    CommandIntel | None,
    tuple,
    ExecutionResult | None,
    dict[str, Any] | None,
]:
    """Run command_shield for RUN_COMMAND. Returns intel, signals, early_block, audit."""
    command = intent.target or (intent.data or {}).get("command", "")
    if not command:
        return None, (), None, None

    report = shield_inspect(command)

    if verbose:
        print("    ┌──────────────────────────────────────────────────────────┐")
        print("    │  COMMAND SHIELD: Deterministic structural analysis        │")
        print(f"    │  Verdict: {report.verdict.value:<47} │")
        if report.signals:
            print(f"    │  Signals: {len(report.signals):<48} │")
        if report.capabilities:
            caps_preview = ", ".join(report.capabilities[:3])
            print(f"    │  Capabilities: {caps_preview[:43]:<43} │")
        print("    └──────────────────────────────────────────────────────────┘")

    if report.verdict == Verdict.CATASTROPHIC:
        reason = "; ".join(s.description for s in report.signals[:3]) or (
            "catastrophic command detected"
        )

        if verbose:
            print("")
            print("    ╔══════════════════════════════════════════════════════════╗")
            print("    ║  COMMAND SHIELD: CATASTROPHIC — REJECTED                 ║")
            print("    ╠══════════════════════════════════════════════════════════╣")
            print(f"    ║  {reason[:56]:<56} ║")
            print("    ╚══════════════════════════════════════════════════════════╝")
            print("")

        audit_entry = {
            "action": intent.action.value,
            "target": intent.target,
            "data": intent.data,
            "reason": intent.reason,
            "decision": "BLOCK",
            "message": f"command_shield: {reason}",
            "decision_path": "command_shield",
            "executed": False,
        }
        return (
            None,
            (),
            ExecutionResult(
                success=False,
                error=f"Blocked by command_shield: {reason}",
                data={
                    "decision": "BLOCK",
                    "reason": reason,
                    "layer": "command_shield",
                },
            ),
            audit_entry,
        )

    terminal_command_signals = report.signals

    code_intel = report.code_intel
    finding_ids: tuple[str, ...] = ()
    if code_intel is not None and code_intel.findings:
        finding_ids = tuple(getattr(f, "finding_id", "") for f in code_intel.findings)
    has_edge_signals = any(
        s.check == "edge" or s.signal_id.startswith("edge:") for s in report.signals
    )
    command_intel = CommandIntel(
        verdict=report.verdict.value,
        capabilities=tuple(report.capabilities),
        has_code_intel_findings=bool(finding_ids),
        code_intel_finding_ids=finding_ids,
        has_edge_signals=has_edge_signals,
    )

    return command_intel, terminal_command_signals, None, None
