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
    IntentSignal,
    IntentFrame,
    RuntimeContextForLLM,
)
from intentframe_core.enums import Reversibility, RiskLevel
from intentframe_bundle_sdk.types import (
    BundleAIContext,
    BundleContext,
    bundle_ai_context_or_empty,
)
from intentframe_bundle_sdk.audit_dump import dump_bundle_ai_context
from intentframe_components.analysis.base import AnalysisEngine
from intentframe_components.prompt import format_intent_data
from intentframe_components.prompt.hardening import PromptHardening
from intentframe_components.prompt.logging import log_output_dump, log_prompt_dump
from intentframe_components.prompt.roles import ANALYSIS_ENGINE_ROLE
from intentframe_components.prompt.runtime_context import merge_runtime_context_sections
from intentframe_prompt_library.library import DEFAULT_AE_SYSTEM_INSTRUCTIONS
import logging

logger = logging.getLogger(__name__)


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


class AIAnalysisEngine(AnalysisEngine):
    """AI-powered Analysis Engine using OpenAI Agents."""

    _hardener = PromptHardening()

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        verbose: bool = True,
    ):
        self.model = model
        self.verbose = verbose
        self._agents: dict[str, Agent] = {}
        self._agent = self._get_agent(DEFAULT_AE_SYSTEM_INSTRUCTIONS)
        self.last_prompt_source: str | None = None
        self.last_prompt_label: str | None = None
        self.last_system_prompt: str | None = None
        self.last_request_prompt: str | None = None
        self.last_llm_output: dict[str, object] | None = None
        self.last_converted_output: dict[str, object] | None = None

    @staticmethod
    def _base_instructions() -> str:
        return DEFAULT_AE_SYSTEM_INSTRUCTIONS

    def _get_agent(self, base_instructions: str) -> Agent:
        if base_instructions not in self._agents:
            self._agents[base_instructions] = Agent(
                name="Analysis Engine",
                instructions=self._hardener.harden_system_prompt(
                    base_instructions=base_instructions,
                    role_preamble=ANALYSIS_ENGINE_ROLE,
                ),
                model=self.model,
                output_type=AIAnalysisOutput,
                model_settings=ModelSettings(temperature=0),
            )
        return self._agents[base_instructions]

    async def analyze(
        self,
        intent: IntentFrame,
        *,
        active_domains: set[str] | None = None,
        runtime_context_for_llm: RuntimeContextForLLM = (),
        bundle_context: BundleContext | None = None,
        bundle_ai_context: BundleAIContext | None = None,
    ) -> AnalysisReport:
        """Analyze what an intent will REALLY do via full AI analysis."""
        self.last_prompt_source = None
        self.last_prompt_label = None
        self.last_system_prompt = None
        self.last_request_prompt = None
        self.last_llm_output = None
        self.last_converted_output = None

        ai_ctx = bundle_ai_context_or_empty(bundle_ai_context)

        if self.verbose:
            for hint in ai_ctx.ae_log_hints:
                print(f"    │  {hint}")

        prompt = self._build_analysis_prompt(
            intent,
            ai_ctx,
            active_domains=active_domains,
            runtime_context_for_llm=runtime_context_for_llm,
        )

        system_instructions = self._resolve_system_instructions(ai_ctx)
        prompt_source = self._resolve_prompt_source(ai_ctx)
        prompt_label = self._resolve_prompt_label(ai_ctx)
        self.last_prompt_source = prompt_source
        self.last_prompt_label = prompt_label
        self.last_request_prompt = prompt
        agent = self._get_agent(system_instructions)
        self.last_system_prompt = agent.instructions

        if self.verbose:
            print(
                f"    │  AI analyzing: {intent.action.value} "
                f"(prompt={prompt_source}:{prompt_label})..."
            )

        log_prompt_dump(
            "analysis",
            prompt,
            prompt_source=prompt_source,
            prompt_label=prompt_label,
            system_prompt=agent.instructions,
            bundle_ai_context=dump_bundle_ai_context(ai_ctx),
        )
        result = await Runner.run(agent, prompt)

        ai_output = result.final_output
        self.last_llm_output = ai_output.model_dump(mode="json")
        report = self._convert_to_report(
            intent,
            ai_output,
            intent_signals=list(ai_ctx.ae_intent_signals),
            signal_truncated=ai_ctx.ae_signal_truncated,
        )
        self.last_converted_output = report.model_dump(mode="json")
        log_output_dump(
            "analysis",
            llm_output=self.last_llm_output,
            converted_output=self.last_converted_output,
            prompt_source=prompt_source,
            prompt_label=prompt_label,
        )
        return report

    @staticmethod
    def _resolve_system_instructions(bundle_ai_context: BundleAIContext) -> str:
        if bundle_ai_context.ae_system_instructions:
            return bundle_ai_context.ae_system_instructions
        return DEFAULT_AE_SYSTEM_INSTRUCTIONS

    @staticmethod
    def _resolve_prompt_source(bundle_ai_context: BundleAIContext) -> str:
        return "bundle" if bundle_ai_context.ae_system_instructions else "fallback_default"

    @staticmethod
    def _resolve_prompt_label(bundle_ai_context: BundleAIContext) -> str:
        return bundle_ai_context.ae_prompt_label or "fallback_default"

    def _build_analysis_prompt(
        self,
        intent: IntentFrame,
        bundle_ai_context: BundleAIContext,
        *,
        active_domains: set[str] | None = None,
        runtime_context_for_llm: RuntimeContextForLLM = (),
    ) -> str:
        """Build hardened per-request prompt; bundle supplies external Context text."""
        context_lines = [
            f"Action: {intent.action.value}",
            f"Agent: {intent.agent_type or intent.agent_id}",
            f"Task: {intent.task_description or 'Not specified'}",
        ]
        if bundle_ai_context.ae_external_context:
            context_lines.append(bundle_ai_context.ae_external_context)

        trusted_sections: dict[str, str] = {
            "Context": "\n".join(context_lines),
        }

        if active_domains:
            domains_str = ", ".join(sorted(active_domains))
            trusted_sections["Active Domains"] = (
                f"The system has rules for these domains: {domains_str}\n"
                "Pay special attention to whether this action falls under any of "
                "these domains. If it does, include the matching domain(s) in your "
                "semantic_domains output. This is a hint — still classify any other "
                "domains you observe."
            )

        merge_runtime_context_sections(trusted_sections, runtime_context_for_llm)

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
        *,
        intent_signals: list[IntentSignal] | None = None,
        signal_truncated: bool = False,
    ) -> AnalysisReport:
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
            intent_signals=intent_signals or [],
            ae_output_anomaly=anomaly,
            report_integrity_flags=(
                ["intent_signals_truncated"] if signal_truncated else []
            ),
        )

    def _detect_overflow(self, ai_output: AIAnalysisOutput) -> bool:
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
