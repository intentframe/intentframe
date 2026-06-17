"""Optional ShellCheck binary integration.

Invokes shellcheck as a subprocess, parses JSON output, and returns
Signal objects.  Degrades gracefully if the binary is not installed.

ShellCheck findings are advisory command intel, not verdict-bearing security
signals.  The binary is optional and commonly present on Linux CI but absent on
macOS developer machines; letting it affect verdicts would make classification
depend on host PATH instead of the command itself.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from command_shield.verdict import Signal

logger = logging.getLogger(__name__)

_SHELLCHECK_BIN: str | None = shutil.which("shellcheck")

_SEVERITY_MAP = {
    "error": "shellcheck-error",
    "warning": "shellcheck-warning",
    "info": "shellcheck-info",
    "style": "shellcheck-style",
}


def is_available() -> bool:
    """Return True if the shellcheck binary is on PATH."""
    return _SHELLCHECK_BIN is not None


def run_shellcheck(command: str, *, timeout: float = 5.0) -> list[Signal]:
    """Pipe *command* through shellcheck and return findings as Signals.

    Returns an empty list if shellcheck is not installed or fails.
    """
    if not _SHELLCHECK_BIN:
        return []

    try:
        result = subprocess.run(
            [_SHELLCHECK_BIN, "--shell=bash", "-f", "json1", "-"],
            input=command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        logger.debug("shellcheck invocation failed", exc_info=True)
        return []

    if not result.stdout:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    signals: list[Signal] = []
    comments = data.get("comments", []) if isinstance(data, dict) else data
    for entry in comments:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code", "")
        level = entry.get("level", "info")
        message = entry.get("message", "")
        signals.append(Signal(
            check="shellcheck",
            signal_id=f"SC{code}",
            description=f"[{level}] {message}",
            evidence=f"line {entry.get('line', '?')}, col {entry.get('column', '?')}",
        ))

    return signals
