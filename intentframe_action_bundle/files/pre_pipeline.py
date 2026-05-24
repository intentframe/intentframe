"""Files bundle pre-pipeline — FileIntel for WRITE_FILE-family actions."""

from __future__ import annotations

from intentframe_action_bundle.files.evidence import FileIntel
from intentframe_core.types import IntentFrame

from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
from intentframe_action_bundle.files.file_intel import build_file_intel


def run_files_pre_pipeline(
    intent: IntentFrame,
    *,
    verbose: bool = False,
) -> FileIntel | None:
    if intent.action.value not in WRITE_FILE_ACTIONS:
        return None

    data = intent.data or {}
    content = data.get("content")
    if not isinstance(content, str):
        return None

    file_intel = build_file_intel(content, intent.target, intent.action.value)

    if verbose and file_intel is not None:
        print("    ┌──────────────────────────────────────────────────────────┐")
        print("    │  FILE SHIELD: Deterministic payload inspection           │")
        print(f"    │  Language: {(file_intel.language or 'unknown'):<45} │")
        print(
            f"    │  Binary: {str(file_intel.is_binary):<8} "
            f"Oversized: {str(file_intel.is_oversized):<8} "
            f"Size: {file_intel.size_bytes:<14} │"
        )
        if file_intel.has_code_intel_findings:
            ids = ", ".join(file_intel.code_intel_finding_ids)[:40]
            print(f"    │  Findings: {ids:<45} │")
        print("    └──────────────────────────────────────────────────────────┘")

    return file_intel
