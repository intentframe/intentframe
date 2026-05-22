"""Bundle-owned trusted prompt sections for the Analysis Engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intentframe_action_bundle.evidence import CommandIntel, FileIntel

if TYPE_CHECKING:
    from intentframe_core.types import IntentFrame
    from intentframe_bundle_sdk.types import BundleContext


def render_context_section(intent: IntentFrame, ctx: BundleContext) -> str:
    """Build the ``Context`` trusted block (parity with legacy AE renderer)."""
    lines = [
        f"Action: {intent.action.value}",
        f"Agent: {intent.agent_type or intent.agent_id}",
        f"Task: {intent.task_description or 'Not specified'}",
    ]
    _append_terminal_signals(lines, ctx.terminal_command_signals)
    if ctx.file_intel is not None:
        _append_file_intel(lines, ctx.file_intel)
    return "\n".join(lines)


def _append_terminal_signals(lines: list[str], terminal_command_signals: tuple) -> None:
    if not terminal_command_signals:
        return
    lines.append(
        "\nTERMINAL COMMAND — STRUCTURAL SIGNALS:\n"
        "Before this command reached you, deterministic static analysis "
        "(AST parsing, pattern matching, normalisation) detected the "
        "following structural concerns. Factor them into your risk "
        "assessment and hidden-behavior analysis:"
    )
    for sig in terminal_command_signals:
        line = f"  - [{sig.check}:{sig.signal_id}] {sig.description}"
        if sig.evidence:
            line += f"  (evidence: {sig.evidence[:120]})"
        lines.append(line)


def _append_file_intel(lines: list[str], file_intel: FileIntel) -> None:
    lines.append(
        "\nWRITE_FILE — PAYLOAD SIGNALS:\n"
        "Deterministic code inspection of the write PAYLOAD "
        "(language sniff, binary guard, AST / regex analyzers) "
        "produced the facts below.  Factor them into your "
        "hidden-behavior and risk analysis — especially findings "
        "on code payloads and oversized / binary content:"
    )
    lines.append(
        f"  - language={file_intel.language or 'unknown'} "
        f"is_binary={file_intel.is_binary} "
        f"is_oversized={file_intel.is_oversized} "
        f"size_bytes={file_intel.size_bytes}"
    )
    if file_intel.signal_ids:
        lines.append(f"  - signals: {', '.join(file_intel.signal_ids)}")
    if file_intel.has_code_intel_findings:
        ids = ", ".join(file_intel.code_intel_finding_ids) or "(unnamed)"
        lines.append(f"  - code-intel findings: {ids}")

    lines.append(
        "\nWRITE_FILE — DESTINATION SIGNALS:\n"
        "Deterministic probe of the TARGET path.  "
        "``destination_exists`` is tri-state: ``true`` = present, "
        "``false`` = absent, ``unknown`` = could not check.  Apply "
        "the reversibility / deletion rules accordingly:"
    )
    exists_str = (
        "unknown"
        if file_intel.destination_exists is None
        else str(file_intel.destination_exists).lower()
    )
    kind_str = file_intel.destination_kind or "unknown"
    lines.append(
        f"  - destination_exists={exists_str} "
        f"destination_kind={kind_str}"
    )
    symlink_target = (
        file_intel.symlink_target_real_path
        if file_intel.symlink_target_real_path
        else "n/a"
    )
    lines.append(
        f"  - is_symlink={str(file_intel.is_symlink).lower()} "
        f"symlink_target_real_path={symlink_target}"
    )
    parent_str = file_intel.parent_kind or "unknown"
    lines.append(f"  - parent_kind={parent_str}")

    lines.append(
        "\nWRITE_FILE — PATH SEMANTICS:\n"
        "Deterministic classification of the target PATH, "
        "independent of what is at the destination today:"
    )
    lines.append(
        f"  - path_category={file_intel.path_category or 'unknown'} "
        f"hits_floor_deny_prefix="
        f"{str(file_intel.hits_floor_deny_prefix).lower()}"
    )
    ext_str = file_intel.extension or "none"
    lines.append(f"  - extension={ext_str}")


def build_ae_trusted_sections(intent: IntentFrame, ctx: BundleContext) -> dict[str, str]:
    """Trusted sections contributed by the action bundle for AE prompts."""
    return {"Context": render_context_section(intent, ctx)}

