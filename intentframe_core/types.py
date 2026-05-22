"""
Data Structures for IntentFrame System

All models used to pass information between layers.
Pydantic BaseModel for automatic JSON serialization over HTTP.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from action_registry import ActionType
from intentframe_core.enums import Decision, Reversibility, RiskLevel
from policy_registry.models import ActionPermission, DomainConstraintTypes, SemanticIntentLimit

TERMINAL_COMMAND_SIGNALS_MAX_ITEMS = 32
TERMINAL_COMMAND_SIGNAL_VALUE_MAX_LEN = 300


class IntentFrame(BaseModel):
    """
    The 'prescription slip' - what the Agent wants to do.

    Created by Actor from unstructured agent request.
    This is the structured, signed representation of intent.
    """
    action: ActionType
    target: str
    data: Optional[Dict[str, Any]] = None
    reason: str = ""

    agent_id: str = ""
    session_id: str = ""
    sequence_id: int = 0
    timestamp: str = ""

    task_description: str = ""
    authorized_by: str = ""
    agent_type: str = ""
    actor_verified: bool = False

    signature: str = ""


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

    terminal_command_signals: List[Dict[str, str]] = Field(default_factory=list)

    ae_output_anomaly: bool = False

    @staticmethod
    def clip_terminal_command_signals(
        signals: List[Dict[str, str]],
    ) -> tuple[List[Dict[str, str]], bool]:
        """Enforce the shield-side input bound on serialized signals.

        Returns the clipped list plus an ``overflow`` flag.  The flag
        is lifted into :pyattr:`ae_output_anomaly` by the caller when
        truncation occurred, so Guardian treats the report with
        elevated suspicion.  No caller should ever produce an
        overflowing list today — this is defense-in-depth against a
        future shield change or a malformed round-trip.
        """
        if not signals:
            return [], False
        overflow = False
        if len(signals) > TERMINAL_COMMAND_SIGNALS_MAX_ITEMS:
            signals = signals[:TERMINAL_COMMAND_SIGNALS_MAX_ITEMS]
            overflow = True
        clipped: List[Dict[str, str]] = []
        for item in signals:
            if not isinstance(item, dict):
                continue
            capped: Dict[str, str] = {}
            for k, v in item.items():
                sv = str(v) if v is not None else ""
                if len(sv) > TERMINAL_COMMAND_SIGNAL_VALUE_MAX_LEN:
                    sv = sv[:TERMINAL_COMMAND_SIGNAL_VALUE_MAX_LEN]
                    overflow = True
                capped[str(k)] = sv
            clipped.append(capped)
        return clipped, overflow


class ValidationResult(BaseModel):
    """
    Guardian's decision after validating an IntentFrame.

    Decisions:
        ALLOW  - Action is authorized, execute as-is (or with modified_intent).
        BLOCK  - Hard policy violation, action rejected.

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

    modified_intent: Optional[IntentFrame] = None


class ExecutionResult(BaseModel):
    """Result from Executor after performing an action."""
    success: bool
    data: Any = None
    error: Optional[str] = None

    execution_id: str = ""
    timestamp: str = ""


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
    domain_constraints: Dict[str, DomainConstraintTypes] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    and user policies.  Includes virtual filesystem paths from the
    Resource Registry so the agent knows its filesystem vocabulary.
    """
    user_id: str = ""
    agent_id: str = ""
    allowed_actions: Dict[str, ActionPermission] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    guardrails: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    available_actions: List[str] = Field(default_factory=list)

    virtual_paths: List[str] = Field(default_factory=list)
    path_permissions: Dict[str, str] = Field(default_factory=dict)

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

        if self.virtual_paths:
            lines.append("\n## Default Filesystem for File Operations")
            lines.append("Use these paths for all file operations (read_file, write_file, etc.).")
            for vp in self.virtual_paths:
                perm = self.path_permissions.get(vp, "read")
                lines.append(f"- {vp} ({perm})")
            lines.append("\nExample: /home/Documents/report.md, /home/Desktop/notes.txt")
            lines.append("Use them exactly as provided without adding extra username directories.")

            if "RUN_COMMAND" in self.allowed_actions:
                lines.append("\n### Terminal (run_command)")
                lines.append("Shell commands operate on the real host OS filesystem, NOT the file-operation paths above.")
                lines.append("- Do not assume the file-operation paths will work inside shell commands.")
                lines.append("- Discover and use real host paths for shell commands.")

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
