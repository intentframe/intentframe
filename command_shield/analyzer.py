"""Full analysis orchestrator for command_shield.

Chains: normalize -> pattern match -> AST decompose -> indirection
-> external tools -> final verdict.
"""

from __future__ import annotations

from command_shield.patterns import match_patterns
from command_shield.structural import decompose, normalize
from command_shield.verdict import CommandReport, Signal, Verdict


def analyze(command: str) -> CommandReport:
    """Run the full analysis pipeline on *command*.

    Used by the runtime before the IntentFrame pipeline.
    """
    if not command or not command.strip():
        return CommandReport(
            verdict=Verdict.SAFE,
            command=command,
            normalized_command="",
        )

    all_signals: list[Signal] = []

    # 1. Normalize
    normalized = normalize(command)

    # 2. Pattern match on normalized command
    verdict, pattern_signals = match_patterns(normalized)
    all_signals.extend(pattern_signals)
    if verdict is Verdict.CATASTROPHIC:
        return CommandReport(
            verdict=Verdict.CATASTROPHIC,
            command=command,
            normalized_command=normalized,
            signals=tuple(all_signals),
        )

    # Also pattern-match the original (catches patterns broken by shlex)
    if normalized != command:
        orig_verdict, orig_signals = match_patterns(command)
        for sig in orig_signals:
            if sig not in all_signals:
                all_signals.append(sig)
        if orig_verdict is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(all_signals),
            )

    # 3. Structural decomposition (bashlex AST / shlex fallback)
    sub_commands, structural_signals, indirections = decompose(command)
    all_signals.extend(structural_signals)

    # 4. Sub-command pattern check
    for sub in sub_commands:
        sub_normalized = normalize(sub)
        sub_verdict, sub_signals = match_patterns(sub_normalized)
        all_signals.extend(sub_signals)
        if sub_verdict is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(all_signals),
                sub_commands=tuple(sub_commands),
            )

    # 5. Indirection re-check (inner payloads through normalize + pattern match)
    for payload in indirections:
        payload_normalized = normalize(payload)
        payload_verdict, payload_signals = match_patterns(payload_normalized)
        all_signals.extend(payload_signals)
        if payload_verdict is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(all_signals),
                sub_commands=tuple(sub_commands),
            )
        # Also try the original payload (nested quotes may confuse shlex)
        if payload_normalized != payload:
            raw_verdict, raw_signals = match_patterns(payload)
            all_signals.extend(raw_signals)
            if raw_verdict is Verdict.CATASTROPHIC:
                return CommandReport(
                    verdict=Verdict.CATASTROPHIC,
                    command=command,
                    normalized_command=normalized,
                    signals=tuple(all_signals),
                    sub_commands=tuple(sub_commands),
                )

    # 6. External tools (optional — ShellCheck)
    try:
        from command_shield.external.shellcheck import run_shellcheck

        sc_signals = run_shellcheck(command)
        all_signals.extend(sc_signals)
    except Exception:  # noqa: BLE001
        pass

    # 7. Final verdict
    if any(s.check == "indirection" for s in all_signals):
        final = Verdict.NEEDS_REVIEW
    elif all_signals:
        final = Verdict.NEEDS_REVIEW
    else:
        final = Verdict.SAFE

    return CommandReport(
        verdict=final,
        command=command,
        normalized_command=normalized,
        signals=tuple(all_signals),
        sub_commands=tuple(sub_commands),
    )
