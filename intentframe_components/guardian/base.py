"""
Layer 4: Guardian ("The Judge")

Policy Enforcer - HYBRID (Local + Cloud)
"""

from abc import ABC, abstractmethod

from intentframe_core.types import (
    AnalysisReport,
    ExecutionContext,
    IntentFrame,
    UserContext,
    ValidationResult,
)
from intentframe_bundle_sdk.types import BundleAIContext, BundleContext


class Guardian(ABC):
    """Layer 4: The Judge - policy enforcement on Analysis Report."""

    @abstractmethod
    async def validate(
        self,
        intent: IntentFrame,
        analysis: AnalysisReport,
        user_context: UserContext,
        *,
        active_domains: set[str] | None = None,
        execution_context: ExecutionContext | None = None,
        bundle_context: BundleContext | None = None,
        bundle_ai_context: BundleAIContext | None = None,
    ) -> ValidationResult:
        """Validate intent against user policies using Analysis Report."""
        pass
