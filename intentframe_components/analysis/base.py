"""
Layer 3: Analysis Engine ("The Brain")

Semantic AI - SECRET, Cloud Only
"""

from abc import ABC, abstractmethod

from intentframe_core.types import (
    AnalysisReport,
    ExecutionContext,
    IntentFrame,
)
from intentframe_bundle_sdk.types import AnalysisContext


class AnalysisEngine(ABC):
    """
    Layer 3: The Brain - SECRET, Cloud Only (FULLY TRUSTED)

    Proprietary AI core that provides deep semantic understanding
    of what actions will ACTUALLY do.
    """

    @abstractmethod
    async def analyze(
        self,
        intent: IntentFrame,
        *,
        active_domains: set[str] | None = None,
        execution_context: ExecutionContext | None = None,
        analysis_context: AnalysisContext | None = None,
    ) -> AnalysisReport:
        """Analyze what an intent will REALLY do (UNDECIDED path only)."""
        pass
