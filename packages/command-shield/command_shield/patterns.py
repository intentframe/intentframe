"""Pattern matching engine for command_shield.

Loads JSON pattern files at import time, compiles regex, provides match API.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from command_shield.verdict import Signal, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

_PATTERNS_DIR = Path(__file__).parent / "patterns"

_CompiledPattern = tuple[re.Pattern[str], str, str, str, str]  # regex, id, verdict, desc, source


def _load_all() -> tuple[_CompiledPattern, ...]:
    """Load and compile every pattern from every JSON file in the patterns/ dir."""
    compiled: list[_CompiledPattern] = []
    for json_path in sorted(_PATTERNS_DIR.glob("*.json")):
        with open(json_path, encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            try:
                rx = re.compile(entry["regex"])
            except re.error:
                continue
            compiled.append((
                rx,
                entry["id"],
                entry["verdict"],
                entry["description"],
                entry.get("source", "unknown"),
            ))
    return tuple(compiled)


COMPILED_PATTERNS: tuple[_CompiledPattern, ...] = _load_all()


def match_patterns(command: str) -> tuple[Verdict | None, list[Signal]]:
    """Match *command* against all compiled patterns.

    Returns the highest verdict found and the list of matching signals.
    A single CATASTROPHIC match short-circuits to CATASTROPHIC.
    """
    signals: list[Signal] = []
    highest: Verdict | None = None

    for rx, pat_id, verdict_str, desc, source in COMPILED_PATTERNS:
        m = rx.search(command)
        if m is None:
            continue

        verdict = Verdict(verdict_str)
        signals.append(Signal(
            check="pattern",
            signal_id=pat_id,
            description=desc,
            evidence=m.group(),
        ))

        if verdict is Verdict.CATASTROPHIC:
            return Verdict.CATASTROPHIC, signals

        if highest is None or verdict is Verdict.NEEDS_REVIEW:
            highest = verdict

    return highest, signals
