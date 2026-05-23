"""Terminal bundle — AE external context and system prompt selection."""

from __future__ import annotations

from intentframe_action_bundle.evidence import CommandIntel
from intentframe_action_bundle.terminal.prompts_ae import _CRITICAL_RUN_COMMAND


def render_terminal_external_context(terminal_command_signals: tuple) -> str:
    """Extra ``Context`` text appended by substrate (legacy parity)."""
    if not terminal_command_signals:
        return ""
    lines: list[str] = [
        "\nTERMINAL COMMAND — STRUCTURAL SIGNALS:\n"
        "Before this command reached you, deterministic static analysis "
        "(AST parsing, pattern matching, normalisation) detected the "
        "following structural concerns. Factor them into your risk "
        "assessment and hidden-behavior analysis:"
    ]
    for sig in terminal_command_signals:
        line = f"  - [{sig.check}:{sig.signal_id}] {sig.description}"
        if sig.evidence:
            line += f"  (evidence: {sig.evidence[:120]})"
        lines.append(line)
    return "\n".join(lines)


def select_terminal_ae_system_instructions(
    command_intel: CommandIntel | None,
) -> tuple[str, str]:
    """Return (system body, audit label) for RUN_COMMAND."""
    del command_intel  # all lanes share the same body today
    return _CRITICAL_RUN_COMMAND, "critical_run_command"
