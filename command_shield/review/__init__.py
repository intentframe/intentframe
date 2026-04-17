"""command_shield.review — back-compat adapter over the unified pipeline.

The extended examination used to live here as its own mini-pipeline.
It now delegates to :func:`command_shield.pipeline.inspect_command_deep`
and simply re-projects the enriched ``CommandReport`` into the legacy
``CommandReview`` shape for callers that still import it.

No policy decisions are made — every finding flows through, the caller
decides what to do.
"""

from __future__ import annotations

from command_shield.config import ShieldConfig
from command_shield.pipeline import inspect_command_deep
from command_shield.review.code_intel import analyze_python_code, analyze_shell_code
from command_shield.review.language import detect_language, extract_inline_code
from command_shield.review.reviewer import review_code
from command_shield.review.types import (
    CodeIntel,
    CommandReview,
    LanguageInfo,
    ReviewFinding,
)
from command_shield.verdict import CommandReport, Signal, Verdict

__all__ = [
    "CodeIntel",
    "CommandReview",
    "LanguageInfo",
    "ReviewFinding",
    "analyze_python_code",
    "analyze_shell_code",
    "detect_language",
    "extract_inline_code",
    "review_code",
    "review_command",
]


def _signal_to_finding(sig: Signal) -> ReviewFinding:
    if sig.check == "pattern":
        severity = "critical"
    elif sig.check == "capability":
        severity = "medium"
    elif sig.check in ("size", "scope"):
        severity = sig.severity or "info"
    else:
        severity = sig.severity if sig.severity != "info" else "high"
    return ReviewFinding(
        source=sig.check,
        finding_id=sig.signal_id,
        severity=severity,
        title=sig.description,
        detail=sig.description,
        evidence=sig.evidence[:200],
        confidence=1.0,
    )


def _report_to_review(report: CommandReport) -> CommandReview:
    """Project the enriched CommandReport onto the legacy CommandReview."""
    findings: list[ReviewFinding] = [_signal_to_finding(s) for s in report.signals]
    if report.code_intel is not None:
        findings.extend(report.code_intel.findings)
    findings.extend(report.reviewer_findings)

    core_report = CommandReport(
        verdict=report.verdict,
        command=report.command,
        normalized_command=report.normalized_command,
        signals=report.signals,
        sub_commands=report.sub_commands,
    )

    return CommandReview(
        command_report=core_report,
        language_info=report.language,
        code_intel=report.code_intel,
        reviewer_findings=report.reviewer_findings,
        reviewer_summary=report.reviewer_summary,
        reviewer_ran=report.reviewer_ran,
        all_findings=tuple(findings),
        elapsed_ms=report.elapsed_ms,
    )


async def review_command(
    command: str,
    *,
    file_content: str | None = None,
    file_path: str | None = None,
    config: ShieldConfig | None = None,
) -> CommandReview:
    """Full examination of a command.

    Deprecated but supported: prefer
    :func:`command_shield.pipeline.inspect_command_deep`, which returns
    a richer ``CommandReport`` directly.  This wrapper exists so older
    callers importing ``CommandReview`` keep working.
    """
    report = await inspect_command_deep(
        command,
        file_content=file_content,
        file_path=file_path,
        config=config,
    )
    return _report_to_review(report)


__all__.append("Verdict")  # re-export for legacy callers
