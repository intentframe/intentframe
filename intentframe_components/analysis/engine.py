"""
AI-Powered Analysis Engine

Uses OpenAI Agents to semantically understand what an intent will REALLY do.

This is the "brain" of the system - it provides UNDERSTANDING, not decisions.
Guardian uses this understanding to make policy decisions.

Deterministic ALLOW/BLOCK is handled by the Bundle SDK (DeterministicGuardian)
before this engine runs.  The AE only executes on UNDECIDED intents.
"""

from enum import IntEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from agents import Agent, ModelSettings, Runner

from intentframe_core.types import (
    AnalysisReport,
    ExecutionContext,
    IntentFrame,
)
from intentframe_core.enums import Reversibility, RiskLevel
from intentframe_bundle_sdk.types import AnalysisContext, analysis_context_or_empty
from intentframe_components.analysis.base import AnalysisEngine
from intentframe_components.prompt import format_intent_data
from intentframe_components.prompt.hardening import PromptHardening
from intentframe_components.prompt.library import (
    ANALYSIS_PROMPT_IDS,
    ANALYSIS_PROMPTS,
)
from intentframe_components.prompt.logging import log_prompt_dump
from intentframe_components.prompt.roles import ANALYSIS_ENGINE_ROLE
import logging

logger = logging.getLogger(__name__)


# ============================================================
# AE Output Field Limits
# ============================================================
# OpenAI structured output enforces these via JSON Schema maxLength /
# maxItems.  The model writes complete text within the budget — no
# post-hoc truncation needed.  These limits are generous: legitimate
# AE output rarely exceeds half the cap.  They exist to structurally
# bound the surface available for a transitive injection payload.

class AEFieldLimit(IntEnum):
    STATED_INTENT = 400
    ACTUAL_BEHAVIOR = 600
    RISK_REASON = 400
    SCOPE_ANALYSIS = 400
    RECOMMENDATION = 600
    HIDDEN_BEHAVIOR_ITEM = 300
    HIDDEN_BEHAVIORS_MAX_ITEMS = 10
    SEMANTIC_DOMAIN_ITEM = 80
    SEMANTIC_DOMAINS_MAX_ITEMS = 15


# ============================================================
# Structured Output for AI Analysis
# ============================================================

_BoundedBehavior = Annotated[str, StringConstraints(max_length=AEFieldLimit.HIDDEN_BEHAVIOR_ITEM)]
_BoundedDomain = Annotated[str, StringConstraints(max_length=AEFieldLimit.SEMANTIC_DOMAIN_ITEM)]


class AIAnalysisOutput(BaseModel):
    """Structured output from the AI Analysis Agent"""

    stated_intent: str = Field(
        max_length=AEFieldLimit.STATED_INTENT,
        description="One sentence: what the agent claims to want to do",
    )
    actual_behavior: str = Field(
        max_length=AEFieldLimit.ACTUAL_BEHAVIOR,
        description="What this action will ACTUALLY do in the real world",
    )

    risk_level: str = Field(
        description="Risk level: LOW, MEDIUM, HIGH, or CRITICAL",
    )
    risk_reason: str = Field(
        max_length=AEFieldLimit.RISK_REASON,
        description="Brief explanation of why this risk level was assigned",
    )

    reversibility: str = Field(
        description="How reversible is this action: FULLY_REVERSIBLE, PARTIALLY_REVERSIBLE, TIME_LIMITED, IRREVERSIBLE, or UNKNOWN",
    )

    hidden_behaviors: list[_BoundedBehavior] = Field(
        default_factory=list,
        max_length=AEFieldLimit.HIDDEN_BEHAVIORS_MAX_ITEMS,
        description="Any hidden or non-obvious behaviors this action might cause",
    )

    scope_analysis: str = Field(
        max_length=AEFieldLimit.SCOPE_ANALYSIS,
        description="What resources/data will this action affect?",
    )
    scope_mismatch: bool = Field(
        default=False,
        description="Does the actual scope exceed what was stated/expected?",
    )

    semantic_domains: list[_BoundedDomain] = Field(
        default_factory=list,
        max_length=AEFieldLimit.SEMANTIC_DOMAINS_MAX_ITEMS,
        description="Human-level domains this action falls under: spending, communication, deletion, data_access, scheduling, etc. Empty list if none apply clearly.",
    )

    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this analysis (0.0 to 1.0)",
    )
    recommendation: str = Field(
        max_length=AEFieldLimit.RECOMMENDATION,
        description="One-sentence neutral summary of the analysis (no allow/block language)",
    )


# ============================================================
# AI Analysis Engine
# ============================================================

class AIAnalysisEngine(AnalysisEngine):
    """
    AI-powered Analysis Engine using OpenAI Agents.
    
    Provides deep semantic understanding of:
    - What actions will ACTUALLY do
    - Hidden or non-obvious behaviors
    - Risk factors
    - Reversibility
    
    Does NOT make allow/block decisions - that's Guardian's job.

    Deterministic ALLOW/BLOCK is handled by action bundles via
    DeterministicGuardian before this engine is invoked.
    """

    _hardener = PromptHardening()

    # ── Model settings note ──────────────────────────────────────
    # The Agents SDK passes ModelSettings fields to the OpenAI Responses
    # API via a _non_null_or_omit() pattern: any field left as None is
    # omitted from the request entirely, falling back to the API's own
    # default (temperature=1.0, top_p=1.0, etc.).
    #
    # For standard completion models (gpt-4o-mini, gpt-4.1, etc.)
    # temperature=0 gives greedy decoding — always picks the highest-
    # probability token.  This is the single biggest lever for
    # reproducibility (~95%+ identical outputs on identical inputs).
    # OpenAI recommends not setting both temperature and top_p, and
    # with temperature=0 top_p is irrelevant, so we leave it as None.
    #
    # GPT-5 family models are reasoning models and do NOT accept
    # temperature — use ModelSettings(reasoning=Reasoning(effort=...))
    # instead.  See the Guardian engine for that pattern.

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        verbose: bool = True,
    ):
        self.model = model
        self.verbose = verbose

        # Build one Agent per prompt id.  N is tiny (4 in the current library), Agents
        # are cheap, and this keeps per-request selection an O(1) dict
        # lookup with zero allocation.  The role preamble and hardening
        # wrapper are identical across ids — only the base_instructions
        # body differs per lane.
        self._agents: dict[str, Agent] = {
            pid: Agent(
                name=f"Analysis Engine ({pid})",
                instructions=self._hardener.harden_system_prompt(
                    base_instructions=body,
                    role_preamble=ANALYSIS_ENGINE_ROLE,
                ),
                model=self.model,
                output_type=AIAnalysisOutput,
                model_settings=ModelSettings(temperature=0),
            )
            for pid, body in ANALYSIS_PROMPTS.items()
        }
        # Back-compat: tests and callers that reach for `self._agent`
        # get the standard lane.  The default for anything that doesn't
        # know about prompt routing.
        self._agent = self._agents["standard"]

        # Last-used prompt id, populated by analyze().  The pipeline
        # reads this for audit only; concurrent writes are bounded by
        # the runtime's per-request asyncio.Lock.  Reset at the start
        # of every analyze() call so stale values never leak across
        # requests.
        self.last_prompt_id: str | None = None

    @staticmethod
    def _base_instructions() -> str:
        """Return the standard-lane AE system-prompt body.

        Kept as a thin facade over :data:`ANALYSIS_PROMPTS` so existing
        tests and external callers that reach for this static method
        keep working unchanged.  The full set of lane bodies lives in
        :mod:`intentframe_components.prompt.library.analysis`.
        """
        return ANALYSIS_PROMPTS["standard"]

    # ── Main analysis entry point ────────────────────────────────────

    async def analyze(
        self,
        intent: IntentFrame,
        *,
        active_domains: set[str] | None = None,
        execution_context: ExecutionContext | None = None,
        analysis_context: AnalysisContext | None = None,
    ) -> AnalysisReport:
        """
        Analyze what an intent will REALLY do via full AI analysis.

        Called only when DeterministicGuardian returned UNDECIDED.
        Trusted deterministic context is supplied by the action bundle
        via ``analysis_context`` (``trusted_sections``).
        """
        self.last_prompt_id = None

        ctx = analysis_context_or_empty(analysis_context)
        terminal_command_signals = ctx.terminal_command_signals

        if terminal_command_signals and self.verbose:
            print(
                f"    │  Terminal command signals ({len(terminal_command_signals)}) "
                f"— enriching AI prompt"
            )

        prompt = self._build_analysis_prompt(
            intent,
            ctx,
            active_domains=active_domains,
            execution_context=execution_context,
        )

        prompt_id = self._resolve_prompt_id(ctx)
        self.last_prompt_id = prompt_id
        agent = self._agents[prompt_id]

        if self.verbose:
            print(f"    │  AI analyzing: {intent.action.value} (prompt={prompt_id})...")

        log_prompt_dump("analysis", prompt, prompt_id=prompt_id)
        result = await Runner.run(agent, prompt)

        return self._convert_to_report(
            intent, result.final_output,
            terminal_command_signals=terminal_command_signals,
        )

    def _resolve_prompt_id(self, analysis_context: AnalysisContext) -> str:
        """Use bundle-selected prompt id when set; else ``standard``."""
        pid = analysis_context.ae_prompt_id
        if pid is None:
            return "standard"
        if pid not in ANALYSIS_PROMPT_IDS:
            logger.warning(
                "Bundle returned unknown AE prompt id %r; falling back to 'standard'",
                pid,
            )
            return "standard"
        return pid

    def _build_analysis_prompt(
        self,
        intent: IntentFrame,
        analysis_context: AnalysisContext,
        *,
        active_domains: set[str] | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> str:
        """Build a hardened prompt — bundle supplies action-specific trusted text."""
        trusted_sections = dict(analysis_context.trusted_sections)

        if active_domains:
            domains_str = ", ".join(sorted(active_domains))
            trusted_sections["Active Domains"] = (
                f"The system has rules for these domains: {domains_str}\n"
                "Pay special attention to whether this action falls under any of "
                "these domains. If it does, include the matching domain(s) in your "
                "semantic_domains output. This is a hint — still classify any other "
                "domains you observe."
            )

        if execution_context and execution_context.executor_running_as_root:
            trusted_sections["Execution Privilege"] = (
                "The executor is running as root (uid=0). All commands execute "
                "with full root privileges. Assess blast radius accordingly — "
                "even benign-looking commands can cause system-wide damage when "
                "run as root. The agent should never use sudo; if sudo appears "
                "in the command, flag it as a hidden behavior."
            )

        # ── Untrusted: agent-controlled fields ────────────────────
        untrusted = {"Target": intent.target, "Reason": intent.reason}

        data_section = format_intent_data(intent.data)
        if data_section:
            untrusted["Data"] = data_section

        return self._hardener.build_hardened_prompt(
            trusted_sections=trusted_sections,
            untrusted_fields=untrusted,
            closing_instruction="Analyze what this action will REALLY do.",
        )
    
    _FIELD_BOUNDS: dict[str, int] = {
        "stated_intent": AEFieldLimit.STATED_INTENT,
        "actual_behavior": AEFieldLimit.ACTUAL_BEHAVIOR,
        "risk_reason": AEFieldLimit.RISK_REASON,
        "scope_analysis": AEFieldLimit.SCOPE_ANALYSIS,
        "recommendation": AEFieldLimit.RECOMMENDATION,
    }
    _LIST_BOUNDS: dict[str, tuple[int, int]] = {
        "hidden_behaviors": (AEFieldLimit.HIDDEN_BEHAVIORS_MAX_ITEMS, AEFieldLimit.HIDDEN_BEHAVIOR_ITEM),
        "semantic_domains": (AEFieldLimit.SEMANTIC_DOMAINS_MAX_ITEMS, AEFieldLimit.SEMANTIC_DOMAIN_ITEM),
    }

    def _convert_to_report(
        self,
        intent: IntentFrame,
        ai_output: AIAnalysisOutput,
        terminal_command_signals: tuple = (),
    ) -> AnalysisReport:
        """Convert AI output to AnalysisReport format.

        Includes a deterministic backstop: if any field exceeds the
        schema-defined bound (which should never happen when OpenAI
        structured output is enforcing maxLength), the report is flagged
        with ae_output_anomaly so Guardian treats it as elevated risk.
        """
        anomaly = self._detect_overflow(ai_output)

        risk_level_map = {
            "LOW": RiskLevel.LOW,
            "MEDIUM": RiskLevel.MEDIUM,
            "HIGH": RiskLevel.HIGH,
            "CRITICAL": RiskLevel.CRITICAL,
        }
        risk_level = risk_level_map.get(ai_output.risk_level.upper(), RiskLevel.MEDIUM)

        reversibility_map = {
            "FULLY_REVERSIBLE": Reversibility.FULLY_REVERSIBLE,
            "PARTIALLY_REVERSIBLE": Reversibility.PARTIALLY_REVERSIBLE,
            "TIME_LIMITED": Reversibility.TIME_LIMITED,
            "IRREVERSIBLE": Reversibility.IRREVERSIBLE,
            "UNKNOWN": Reversibility.UNKNOWN,
        }
        reversibility = reversibility_map.get(
            ai_output.reversibility.upper(),
            Reversibility.UNKNOWN,
        )

        serialized_signals = [
            {
                "check": s.check,
                "signal_id": s.signal_id,
                "description": s.description,
                "evidence": s.evidence,
            }
            for s in terminal_command_signals
        ]
        clipped_signals, signals_overflow = AnalysisReport.clip_terminal_command_signals(
            serialized_signals
        )

        return AnalysisReport(
            stated_intent=ai_output.stated_intent,
            actual_behaviors=[{
                "action": intent.action.value,
                "actual_behavior": ai_output.actual_behavior,
                "matches_intent": not ai_output.scope_mismatch,
            }],
            requested_scope=[intent.target],
            actual_scope=[ai_output.scope_analysis],
            scope_mismatch=ai_output.scope_mismatch,
            predicted_outcomes={
                "risk_reason": ai_output.risk_reason,
            },
            hidden_behaviors=ai_output.hidden_behaviors,
            risk_factors={"overall": risk_level},
            reversibility=reversibility,
            semantic_domains=ai_output.semantic_domains,
            confidence=ai_output.confidence,
            recommendation=ai_output.recommendation,
            terminal_command_signals=clipped_signals,
            ae_output_anomaly=anomaly or signals_overflow,
        )

    def _detect_overflow(self, ai_output: AIAnalysisOutput) -> bool:
        """Return True if any AI output field exceeds its schema bound."""
        for field_name, limit in self._FIELD_BOUNDS.items():
            if len(getattr(ai_output, field_name, "")) > limit:
                return True
        for field_name, (max_items, per_item_limit) in self._LIST_BOUNDS.items():
            items = getattr(ai_output, field_name, [])
            if len(items) > max_items:
                return True
            if any(len(item) > per_item_limit for item in items):
                return True
        return False
