"""Action-agnostic pre-pipeline — delegates to per-family bundles."""

from __future__ import annotations

from action_registry.types import ActionType

from intentframe_action_bundle.email.enrich import enrich_intent as enrich_email_intent
from intentframe_action_bundle.files.pre_pipeline import run_files_pre_pipeline
from intentframe_action_bundle.terminal.pre_pipeline import run_terminal_pre_pipeline
from intentframe_action_bundle.types import PrePipelineResult


async def run_pre_pipeline(
    intent,
    *,
    verbose: bool = False,
) -> PrePipelineResult:
    """Run all bundle pre-pipeline steps; first catastrophic block wins."""
    command_intel = None
    file_intel = None
    terminal_command_signals: tuple = ()
    audit_entry = None
    early_block = None

    if intent.action.value == ActionType.RUN_COMMAND.value:
        (
            command_intel,
            terminal_command_signals,
            early_block,
            audit_entry,
        ) = run_terminal_pre_pipeline(intent, verbose=verbose)
        if early_block is not None:
            return PrePipelineResult(
                intent=intent,
                command_intel=command_intel,
                terminal_command_signals=terminal_command_signals,
                early_block=early_block,
                audit_entry=audit_entry,
            )

    file_intel = run_files_pre_pipeline(intent, verbose=verbose)

    intent = await enrich_email_intent(intent)

    return PrePipelineResult(
        intent=intent,
        command_intel=command_intel,
        file_intel=file_intel,
        terminal_command_signals=terminal_command_signals,
        early_block=early_block,
        audit_entry=audit_entry,
    )
