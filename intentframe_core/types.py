"""
Data Structures for IntentFrame System

All models used to pass information between layers.
Pydantic BaseModel for automatic JSON serialization over HTTP.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intentframe_core.enums import Decision, Reversibility, RiskLevel
from policy_registry.models import ActionPermission, SemanticIntentLimit

INTENT_SIGNALS_MAX_ITEMS = 32
INTENT_SIGNAL_VALUE_MAX_LEN = 300


class IntentSignal(BaseModel):
    """A single deterministic finding attached to an AnalysisReport.

    Produced by bundles (not the AE LLM) from substrate evidence such as
    command_shield signals.  All fields are bounded so the report cannot
    carry an oversized payload regardless of upstream source.
    """

    source: str = Field(default="", max_length=80)
    check: str = Field(default="", max_length=80)
    signal_id: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=INTENT_SIGNAL_VALUE_MAX_LEN)
    evidence: str = Field(default="", max_length=INTENT_SIGNAL_VALUE_MAX_LEN)


class IntentFrame(BaseModel):
    """
    The 'prescription slip' - what the Agent wants to do.

    Created by Actor from unstructured agent request.
    This is the structured, signed representation of intent.

    ``action`` is an opaque string identifier (e.g. ``"READ_FILE"``). Core does
    not validate it against any taxonomy — that is the agent author's job (they
    may use ``action_registry`` for convenience). Unknown actions fail closed at
    executor dispatch.
    """
    action: str
    target: str
    data: Optional[Dict[str, Any]] = None
    reason: str = ""
    display_subject: str = ""

    agent_id: str = ""
    session_id: str = ""
    sequence_id: int = 0
    timestamp: str = ""

    task_description: str = ""
    authorized_by: str = ""
    agent_type: str = ""
    actor_verified: bool = False

    signature: str = ""


class PromptEvidence(BaseModel):
    """Per-request prompt and LLM forensic evidence for audit logging."""

    prompt_source: Optional[str] = None
    prompt_label: Optional[str] = None
    system_prompt: Optional[str] = None
    request_prompt: Optional[str] = None
    llm_output: Optional[Dict[str, Any]] = None
    converted_output: Optional[Dict[str, Any]] = None


class AnalysisReport(BaseModel):
    """
    Output from Analysis Engine - understanding, NOT decisions.

    Analysis Engine: "What does this action REALLY do?"
    This report feeds into Guardian for policy decisions.
    """
    stated_intent: str = ""
    actual_behaviors: List[Dict[str, Any]] = Field(default_factory=list)

    requested_scope: List[str] = Field(default_factory=list)
    actual_scope: List[str] = Field(default_factory=list)
    scope_mismatch: bool = False

    predicted_outcomes: Dict[str, Any] = Field(default_factory=dict)
    hidden_behaviors: List[str] = Field(default_factory=list)

    risk_factors: Dict[str, RiskLevel] = Field(default_factory=dict)
    reversibility: Reversibility = Reversibility.UNKNOWN

    semantic_domains: List[str] = Field(default_factory=list)

    confidence: float = 0.0
    recommendation: str = ""

    intent_signals: List[IntentSignal] = Field(default_factory=list)

    ae_output_anomaly: bool = False

    report_integrity_flags: List[str] = Field(default_factory=list)
    prompt_evidence: Optional[PromptEvidence] = None


class ValidationResult(BaseModel):
    """
    Guardian's decision after validating an IntentFrame.

    Decisions:
        ALLOW  - Action is authorized.
        BLOCK  - Hard policy violation, action rejected.

    Execution contract: ``IntentFrameRuntime`` always passes the actor-submitted
    frame to ``executor.execute()``. ``modified_intent`` is reserved but unused;
    Guardian validates, it does not rewrite adapter params.

    decision_path identifies which internal path produced this result.
    Used for audit logging and metrics; never affects behavior.
    Reserved values:
        "fast_path"     - Guardian deterministic fast-path ALLOW (safe + no risk flags).
        "ai_path"       - AI Guardian rendered judgment (default).
        "deterministic" - Reserved for the future DeterministicGuardian pre-pass.
    """
    decision: Decision
    intent: IntentFrame
    analysis: Optional[AnalysisReport] = None
    message: str = ""
    decision_path: Literal["fast_path", "ai_path", "deterministic"] = "ai_path"

    modified_intent: Optional[IntentFrame] = None  # unused; runtime executes submitted intent only
    prompt_evidence: Optional[PromptEvidence] = None


class ExecutionResult(BaseModel):
    """Result from Executor after performing an action.

    ``display_summary`` is an optional renderer-friendly string from the
    executor (often newline-separated). The runtime prints it in verbose mode
    without knowing action-specific field names; structured ``data`` remains
    the machine-readable payload.

    Invariant — *every failure carries a reason*: a result with
    ``success=False`` and no ``error`` is an auditability gap (the log can
    no longer explain *why* an action failed). We normalise rather than
    raise: this object is constructed *after* an action has already run, so
    turning a missing-error into an exception here would destroy the audit
    record of a side effect that already happened. Fail-open on the data
    shape, never on the audit trail.
    """
    success: bool
    data: Any = None
    error: Optional[str] = None

    execution_id: str = ""
    timestamp: str = ""
    display_summary: str = ""

    @model_validator(mode="after")
    def _ensure_failure_has_reason(self) -> "ExecutionResult":
        if not self.success and not (self.error or "").strip():
            self.error = "Execution failed without an error message"
        return self


class UserContext(BaseModel):
    """User's policies and permissions, sourced from the Policy Registry.

    The allowed_actions dict IS the policy:
        - Key present → action permitted (with constraints/safe flag).
        - Key absent  → action blocked (deny-by-default).

    No separate approval_limit or allowed_paths — those are now
    embedded in per-category constraints.

    Identity model:
        ``user_id`` is the operator the request is on behalf of.
        ``agent_id`` is the agent making the request (e.g. ``jarvis``).
        Registry lookup uses the ``(user_id, agent_id)`` pair so
        one operator running multiple agents has isolated policies.
    """
    user_id: str = ""
    agent_id: str = ""
    allowed_actions: Dict[str, ActionPermission] = Field(default_factory=dict)
    intent_limits: List[SemanticIntentLimit] = Field(default_factory=list)
    domain_constraints: Dict[str, dict[str, Any]] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMContextSection:
    """One trusted prompt section; label maps to <trusted_context source=\"...\">."""

    label: str
    content: str


RuntimeContextForLLM = tuple[LLMContextSection, ...]


class ExecutionContext(BaseModel):
    """Server-side infrastructure facts about the executor.

    Probed once at startup from the executor's /health endpoint.
    Immutable for the lifetime of the server process.
    Never exposed to agents -- they learn consequences via RuntimeContext.
    """

    model_config = ConfigDict(frozen=True)

    executor_running_as_root: bool = False
    executor_uid: int = -1
    executor_euid: int = -1


class AgentCapabilities(BaseModel):
    """
    Agent's self-description - what it does and needs.

    Sent to the runtime during handshake to get relevant context.
    """
    agent_type: str = ""
    description: str = ""
    capabilities: List[str] = Field(default_factory=list)
    resource_needs: List[str] = Field(default_factory=list)
    action_types: List[str] = Field(default_factory=list)

    version: str = "1.0.0"
    author: str = ""


class RuntimeContext(BaseModel):
    """
    Context provided by IntentFrame runtime after handshake.

    Generated by AI Onboarding Engine based on agent capabilities
    and user policies.
    """
    user_id: str = ""
    agent_id: str = ""
    allowed_actions: Dict[str, ActionPermission] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    guardrails: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    available_actions: List[str] = Field(default_factory=list)

    session_id: str = ""
    timestamp: str = ""

    onboarded_agent_type: str = ""
    onboarding_confidence: float = 0.0

    def to_instructions(self) -> str:
        """Convert context to human-readable instructions for agent system prompt."""
        lines = []

        lines.append("## Your Operating Context")
        lines.append(f"- User: {self.user_id}")

        allowed_list = sorted(self.allowed_actions.keys())
        safe_list = [a for a, p in self.allowed_actions.items() if p.safe]

        lines.append(f"- Allowed Actions: {', '.join(allowed_list)}")
        if safe_list:
            lines.append(f"- Fast-path (safe) Actions: {', '.join(sorted(safe_list))}")

        if self.guardrails:
            lines.append("\n## GUARDRAILS (You MUST follow these)")
            for i, rule in enumerate(self.guardrails, 1):
                lines.append(f"{i}. {rule}")

        if self.warnings:
            lines.append("\n## Warnings")
            for warning in self.warnings:
                lines.append(f"- {warning}")

        if self.metadata:
            lines.append("\n## Additional Policies")
            for key, value in self.metadata.items():
                lines.append(f"- {key}: {value}")

        return "\n".join(lines)
