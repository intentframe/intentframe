"""AE deterministic fast-path — catastrophic RUN_COMMAND patterns."""

from __future__ import annotations

from action_registry.types import ActionType
from intentframe_core.enums import Reversibility, RiskLevel
from intentframe_core.types import AnalysisReport, IntentFrame

CATASTROPHIC_COMMAND_PATTERNS: dict[str, str] = {
    "sudo": "Privilege escalation — runs command as superuser",
    "rm -rf /": "Recursive forced deletion of root filesystem",
    "mkfs": "Filesystem format — destroys all data on target device",
    "dd if=": "Raw disk write — overwrites device blocks directly",
    "> /dev/": "Direct write to device file — bypasses filesystem",
    "chmod 777": "World-writable permissions — removes all access control",
}


def try_catastrophic_report(intent: IntentFrame) -> AnalysisReport | None:
    """Return a deterministic CRITICAL report if the command is catastrophic."""
    if intent.action.value != ActionType.RUN_COMMAND.value:
        return None

    command = (intent.data or {}).get("command", "")
    if not command or (isinstance(command, str) and not command.strip()):
        return None

    for pattern, description in CATASTROPHIC_COMMAND_PATTERNS.items():
        if pattern in command:
            return AnalysisReport(
                stated_intent=f"RUN_COMMAND: {command[:100]}",
                actual_behaviors=[{
                    "action": "RUN_COMMAND",
                    "actual_behavior": description,
                    "matches_intent": True,
                }],
                requested_scope=[command],
                actual_scope=["system-wide"],
                scope_mismatch=False,
                predicted_outcomes={
                    "risk_reason": f"Catastrophic operation: {description}",
                },
                hidden_behaviors=[],
                risk_factors={"overall": RiskLevel.CRITICAL},
                reversibility=Reversibility.IRREVERSIBLE,
                confidence=1.0,
                recommendation=f"Deterministic analysis: catastrophic command ({pattern}).",
            )

    return None
