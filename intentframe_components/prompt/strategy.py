"""
Prompt-id strategy — Guardian routing; AE ids come from bundles via AnalysisContext.
"""

from __future__ import annotations

from typing import Protocol

from intentframe_core.types import AnalysisReport, IntentFrame
from intentframe_components.routing.criticality import is_critical


class PromptStrategy(Protocol):
    """Contract for routing intents to Guardian prompt ids."""

    def select_guardian_prompt_id(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
    ) -> str:
        ...


class DefaultPromptStrategy:
    """Deterministic Guardian prompt-id selector."""

    _GUARDIAN_PRECEDENCE: tuple[str, ...] = (
        "critical",
        "standard",
    )

    def select_guardian_prompt_id(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
    ) -> str:
        del analysis
        if is_critical(intent.action.value):
            return "critical"
        return "standard"


__all__ = [
    "PromptStrategy",
    "DefaultPromptStrategy",
]
