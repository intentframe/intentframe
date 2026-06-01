"""
IntentFrame Core — shared types and enums used across the entire system.

Both the server (``intentframe_server/``) and the Actor SDK
(``intentframe_actor/``) import from here. This package is the neutral
foundation layer: it must not import ``intentframe_native_kit.action_registry`` (the action
taxonomy lives there; ``IntentFrame.action`` is a plain string).

Concrete domain intent schemas (finance, deletion, …) also live in
``intentframe_native_kit.action_registry.domains``; ``intentframe_core.domains`` only exposes
the shared :class:`~intentframe_core.domains.base.DomainSchema` base.
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
