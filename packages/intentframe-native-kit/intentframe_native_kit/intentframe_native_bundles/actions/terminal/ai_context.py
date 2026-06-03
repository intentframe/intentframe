"""Terminal bundle — AE external context and system prompt selection."""

from __future__ import annotations

from intentframe_bundle_sdk import (
    INTENT_SIGNALS_MAX_ITEMS,
    INTENT_SIGNAL_VALUE_MAX_LEN,
    IntentSignal,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.evidence import CommandIntel
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.prompts_ae import _CRITICAL_RUN_COMMAND


def build_terminal_intent_signals(
    signals: tuple,
) -> tuple[list[IntentSignal], bool]:
    """Convert raw command_shield Signal objects into bounded IntentSignal list.

    Returns (clipped_list, truncated).  ``truncated`` is True if any signal was
    dropped (count overflow) or any field value had to be capped (length overflow).
    This is the only place in the codebase that knows about the command_shield
    Signal shape; all other layers work with the generic IntentSignal type.
    """
    if not signals:
        return [], False
    truncated = False
    raw = signals
    if len(raw) > INTENT_SIGNALS_MAX_ITEMS:
        raw = raw[:INTENT_SIGNALS_MAX_ITEMS]
        truncated = True
    result: list[IntentSignal] = []
    for s in raw:
        evidence = s.evidence or ""
        if len(evidence) > INTENT_SIGNAL_VALUE_MAX_LEN:
            evidence = evidence[:INTENT_SIGNAL_VALUE_MAX_LEN]
            truncated = True
        description = s.description or ""
        if len(description) > INTENT_SIGNAL_VALUE_MAX_LEN:
            description = description[:INTENT_SIGNAL_VALUE_MAX_LEN]
            truncated = True
        result.append(IntentSignal(
            source="terminal.command_shield",
            check=s.check or "",
            signal_id=s.signal_id or "",
            description=description,
            evidence=evidence,
        ))
    return result, truncated


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
