"""Fast subset analysis for the executor adapter.

Runs normalize + pattern match + indirection extraction only.
No AST parsing, no external tools.  Returns CATASTROPHIC or PASS.
"""

from __future__ import annotations

import shlex

from command_shield.patterns import match_patterns
from command_shield.structural import normalize
from command_shield.verdict import CommandReport, Verdict

_INTERPRETERS = frozenset({
    "python", "python3", "python2",
    "perl", "ruby", "node",
    "bash", "sh", "zsh", "dash",
    "osascript",
})

_INLINE_FLAGS = frozenset({"-c", "-e", "--eval"})


def quick_check(command: str) -> CommandReport:
    """Fast deterministic check — CATASTROPHIC patterns + indirection only.

    Used by the executor adapter as a last-resort floor.
    """
    if not command or not command.strip():
        return CommandReport(
            verdict=Verdict.SAFE,
            command=command,
            normalized_command="",
        )

    # 1. Normalize
    normalized = normalize(command)

    # 2. Pattern match
    verdict, signals = match_patterns(normalized)
    if verdict is Verdict.CATASTROPHIC:
        return CommandReport(
            verdict=Verdict.CATASTROPHIC,
            command=command,
            normalized_command=normalized,
            signals=tuple(signals),
        )

    # Also check original string
    if normalized != command:
        orig_verdict, orig_signals = match_patterns(command)
        signals.extend(orig_signals)
        if orig_verdict is Verdict.CATASTROPHIC:
            return CommandReport(
                verdict=Verdict.CATASTROPHIC,
                command=command,
                normalized_command=normalized,
                signals=tuple(signals),
            )

    # 3. Indirection extraction + re-check
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    for i, tok in enumerate(tokens):
        cmd = tok.split("/")[-1]
        if cmd in _INTERPRETERS and i + 2 < len(tokens) and tokens[i + 1] in _INLINE_FLAGS:
            payload = tokens[i + 2]
            payload_normalized = normalize(payload)
            pv, _ = match_patterns(payload_normalized)
            if pv is Verdict.CATASTROPHIC:
                return CommandReport(
                    verdict=Verdict.CATASTROPHIC,
                    command=command,
                    normalized_command=normalized,
                    signals=tuple(signals),
                )
            if payload_normalized != payload:
                pv2, _ = match_patterns(payload)
                if pv2 is Verdict.CATASTROPHIC:
                    return CommandReport(
                        verdict=Verdict.CATASTROPHIC,
                        command=command,
                        normalized_command=normalized,
                        signals=tuple(signals),
                    )

    # No catastrophic signals — pass
    return CommandReport(
        verdict=Verdict.SAFE,
        command=command,
        normalized_command=normalized,
        signals=tuple(signals),
    )
