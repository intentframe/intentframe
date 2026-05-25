"""
AI-Powered Onboarding Engine

Uses OpenAI Agents to dynamically generate context for any agent type.

Substrate orchestration only — action-family onboarding copy lives in
native bundles; constraint summaries use the bundle SDK.
"""

from datetime import datetime, timezone
from typing import List

from openai.types.shared import Reasoning
from pydantic import BaseModel, Field

from agents import Agent, ModelSettings, Runner

from intentframe_core.types import AgentCapabilities, RuntimeContext, RuntimeContextForLLM, UserContext
from intentframe_components.onboarding.base import OnboardingEngine
from intentframe_components.prompt.logging import log_prompt_dump
from intentframe_components.prompt.runtime_context import append_runtime_context_sections
from intentframe_bundle_sdk.constraints import describe_action_constraints_from_policy
from intentframe_components.onboarding.instructions import build_onboarding_instructions


# ============================================================
# Structured Output for AI Onboarding
# ============================================================

class AIOnboardingOutput(BaseModel):
    """Structured output from the AI Onboarding Engine"""

    guardrails: List[str] = Field(
        description="List of specific, actionable rules this agent MUST follow based on its capabilities and user policies"
    )

    warnings: List[str] = Field(
        default_factory=list,
        description="Risk warnings about this agent's capabilities (e.g., 'Agent can execute scripts - high risk')"
    )

    relevant_policies: List[str] = Field(
        default_factory=list,
        description="Which user policies are most relevant to this agent's work"
    )

    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this onboarding analysis (0.0 to 1.0)"
    )

    summary: str = Field(
        description="Brief summary of what this agent does and key constraints applied"
    )


# ============================================================
# AI Onboarding Engine
# ============================================================

class AIOnboardingEngine(OnboardingEngine):
    """
    AI-powered Onboarding Engine using OpenAI Agents.

    Handles the handshake between any agent and IntentFrame.
    Action-type guardrail hints and constraint summaries are supplied
    by the action bundle package, not hardcoded here.
    """

    def __init__(self, model: str = "gpt-4o-mini", verbose: bool = True):
        self.model = model
        self.verbose = verbose

    @staticmethod
    def _build_instructions(allowed_action_ids: frozenset[str]) -> str:
        return build_onboarding_instructions(allowed_action_ids)

    @staticmethod
    def _summarize_intent_limits(intent_limits) -> str:
        if not intent_limits:
            return "  None"
        return "\n".join(
            f"  - {limit.raw}"
            for limit in intent_limits
        )

    async def onboard(
        self,
        capabilities: AgentCapabilities,
        user_context: UserContext,
        runtime_context_for_llm: RuntimeContextForLLM = (),
    ) -> RuntimeContext:
        """Perform AI-powered handshake to generate agent context."""
        prompt = self._build_onboarding_prompt(
            capabilities,
            user_context,
            runtime_context_for_llm=runtime_context_for_llm,
        )

        allowed_action_ids = frozenset(user_context.allowed_actions.keys())
        system_instructions = self._build_instructions(allowed_action_ids)

        if self.verbose:
            print(f"\n    [ONBOARDING] AI analyzing agent '{capabilities.agent_type}'...")

        log_prompt_dump("onboarding", prompt, system_prompt=system_instructions)
        agent = Agent(
            name="Onboarding Engine",
            instructions=system_instructions,
            model=self.model,
            output_type=AIOnboardingOutput,
        )
        result = await Runner.run(agent, prompt)
        ai_output: AIOnboardingOutput = result.final_output

        if self.verbose:
            print(f"    [ONBOARDING] Generated {len(ai_output.guardrails)} guardrails")
            if ai_output.warnings:
                print(f"    [ONBOARDING] Warnings: {len(ai_output.warnings)}")
            print(f"    [ONBOARDING] Confidence: {ai_output.confidence:.0%}")

        return self._build_runtime_context(capabilities, user_context, ai_output)

    def _build_onboarding_prompt(
        self,
        capabilities: AgentCapabilities,
        user_context: UserContext,
        runtime_context_for_llm: RuntimeContextForLLM = (),
    ) -> str:
        """Build the prompt for the AI agent."""

        allowed_list = sorted(user_context.allowed_actions.keys())
        safe_list = [a for a, p in user_context.allowed_actions.items() if p.safe]

        constraint_summary_lines: list[str] = []
        for action, perm in user_context.allowed_actions.items():
            if perm.constraints is not None:
                constraint_summary_lines.append(
                    f"  {action}: {describe_action_constraints_from_policy(action, perm)}"
                )

        constraint_str = "\n".join(constraint_summary_lines) if constraint_summary_lines else "  None"
        intent_limit_str = self._summarize_intent_limits(user_context.intent_limits)

        prompt = f"""Generate context and guardrails for this agent:

## AGENT CAPABILITIES

Agent Type: {capabilities.agent_type}
Description: {capabilities.description}
Version: {capabilities.version}

Capabilities: {', '.join(capabilities.capabilities) if capabilities.capabilities else 'Not specified'}
Action Types: {', '.join(capabilities.action_types) if capabilities.action_types else 'Not specified'}
Resource Needs: {', '.join(capabilities.resource_needs) if capabilities.resource_needs else 'Not specified'}

## USER POLICIES

User ID: {user_context.user_id}
Agent ID: {user_context.agent_id}
Allowed Actions: {', '.join(allowed_list)}
Safe (fast-path) Actions: {', '.join(sorted(safe_list)) if safe_list else 'None'}

Constraints:
{constraint_str}

Custom User Rules:
{intent_limit_str}
"""

        if user_context.metadata:
            prompt += "\nMetadata:\n"
            for key, value in user_context.metadata.items():
                prompt += f"  - {key}: {value}\n"

        prompt = append_runtime_context_sections(prompt, runtime_context_for_llm)

        prompt += """

Generate appropriate guardrails for this agent based on its capabilities and the user's policies.
Be specific - reference actual constraints and allowed actions."""

        return prompt

    def _build_runtime_context(
        self,
        capabilities: AgentCapabilities,
        user_context: UserContext,
        ai_output: AIOnboardingOutput
    ) -> RuntimeContext:
        """Build RuntimeContext from AI output."""

        return RuntimeContext(
            user_id=user_context.user_id,
            agent_id=user_context.agent_id,
            allowed_actions=user_context.allowed_actions,
            metadata=user_context.metadata,

            guardrails=ai_output.guardrails,
            warnings=ai_output.warnings,

            available_actions=capabilities.action_types,

            session_id=f"session_{user_context.user_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.now(timezone.utc).isoformat(),

            onboarded_agent_type=capabilities.agent_type,
            onboarding_confidence=ai_output.confidence,
        )
