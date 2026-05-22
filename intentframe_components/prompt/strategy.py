"""
Prompt-id strategy — deterministic routing to AE/Guardian prompt lanes.

AE prompt-id selection delegates to ``intentframe_action_bundle.prompts.registry``
so family-specific routing (terminal, files, critical) lives in bundles.
This module keeps the Protocol, precedence documentation, and Guardian routing.
"""

from __future__ import annotations

from typing import Protocol

from intentframe_action_bundle.prompts.registry import select_ae_prompt_id as bundle_select_ae_prompt_id
from intentframe_core.types import AnalysisReport, CommandIntel, FileIntel, IntentFrame
from intentframe_components.routing.criticality import is_critical


class PromptStrategy(Protocol):
    """Contract for routing intents to AE/Guardian prompt ids."""

    def select_ae_prompt_id(
        self,
        intent: IntentFrame,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        ...

    def select_guardian_prompt_id(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        ...


class DefaultPromptStrategy:
    """Deterministic, capability-aware prompt-id selector."""

    _AE_PRECEDENCE: tuple[str, ...] = (
        "critical_network_mutation",
        "critical_network_probe",
        "critical_run_command",
        "critical_write_file",
        "critical_generic",
        "standard",
    )

    _GUARDIAN_PRECEDENCE: tuple[str, ...] = (
        "critical",
        "standard",
    )

    def select_ae_prompt_id(
        self,
        intent: IntentFrame,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        return bundle_select_ae_prompt_id(intent, command_intel, file_intel)

    def select_guardian_prompt_id(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
        command_intel: CommandIntel | None,
        file_intel: FileIntel | None = None,
    ) -> str:
        del analysis, command_intel, file_intel

        if is_critical(intent.action.value):
            return "critical"
        return "standard"


__all__ = [
    "PromptStrategy",
    "DefaultPromptStrategy",
]
