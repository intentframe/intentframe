"""Files bundle — AE external context and system prompt selection."""

from __future__ import annotations

from intentframe_action_bundle.files.evidence import FileIntel
from intentframe_action_bundle.files.prompts_ae import _CRITICAL_WRITE_FILE


def render_file_external_context(file_intel: FileIntel | None) -> str:
    """Extra ``Context`` text appended by substrate (legacy parity)."""
    if file_intel is None:
        return ""

    lines: list[str] = [
        "\nWRITE_FILE — PAYLOAD SIGNALS:\n"
        "Deterministic code inspection of the write PAYLOAD "
        "(language sniff, binary guard, AST / regex analyzers) "
        "produced the facts below.  Factor them into your "
        "hidden-behavior and risk analysis — especially findings "
        "on code payloads and oversized / binary content:",
        (
            f"  - language={file_intel.language or 'unknown'} "
            f"is_binary={file_intel.is_binary} "
            f"is_oversized={file_intel.is_oversized} "
            f"size_bytes={file_intel.size_bytes}"
        ),
    ]
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
    return "\n".join(lines)


def select_write_file_ae_system_instructions() -> tuple[str, str]:
    return _CRITICAL_WRITE_FILE, "critical_write_file"
