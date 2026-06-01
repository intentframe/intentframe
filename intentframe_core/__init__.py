"""
IntentFrame Core — shared types and enums used across the entire system.

Both the server (intentframe/) and the Actor SDK (intentframe_actor/)
import from here.  This package has zero dependencies on either.
"""

from intentframe_core.enums import Decision, Reversibility, RiskLevel
from intentframe_core.paths import VIRTUAL_HOME, normalize_virtual_path
from intentframe_core.types import (
    AgentCapabilities,
    AnalysisReport,
    ExecutionContext,
    ExecutionResult,
    IntentFrame,
    LLMContextSection,
    RuntimeContext,
    RuntimeContextForLLM,
    UserContext,
    ValidationResult,
)
