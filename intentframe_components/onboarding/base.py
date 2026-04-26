"""
Layer 0: Onboarding Engine ("The Context Builder")

AI-Powered Handshake - Runs BEFORE agent starts working

This is a new layer that handles the handshake between agents and IntentFrame.
It runs ONCE when an agent connects, before any requests are processed.
"""

from abc import ABC, abstractmethod

from intentframe_core.types import AgentCapabilities, ExecutionContext, RuntimeContext, UserContext


class OnboardingEngine(ABC):
    """
    Layer 0: The Context Builder - AI-Powered Handshake

    Handles the initial handshake when an agent connects to IntentFrame.
    Uses AI to dynamically generate appropriate context for ANY agent type.

    Why AI-Powered?
    - Can understand any agent's description (not hardcoded per type)
    - Generates context-aware guardrails based on capabilities
    - Adapts when agent capabilities change
    - Scales to unknown agent types without code changes

    Responsibilities:
    - Receive agent capabilities (what the agent does)
    - Analyze capabilities against user policies
    - Generate relevant guardrails for the agent
    - Return RuntimeContext with everything agent needs

    HAS: AI understanding of agent capabilities, policy knowledge
    HAS NOT: Ability to execute actions, direct resource access

    OUTPUT: RuntimeContext (allowed actions, guardrails, relevant policies)

    This runs ONCE at agent startup, not per-request.
    """

    @abstractmethod
    async def onboard(
        self,
        capabilities: AgentCapabilities,
        user_context: UserContext,
        execution_context: ExecutionContext | None = None,
    ) -> RuntimeContext:
        """
        Perform AI-powered handshake to generate agent context.

        Input:
        - capabilities: What the agent says it does (type, description, actions)
        - user_context: User's allowed actions with constraints and safe flags
        - execution_context: Immutable server-side facts about the executor
          (privilege level, uid/euid).  Allows onboarding to inject
          appropriate guardrails when the executor runs as root.

        AI Processing:
        - Understand agent's purpose from description
        - Match capabilities against user policies
        - Identify relevant guardrails for this agent type
        - Generate specific, actionable rules

        Output:
        - RuntimeContext with:
          - allowed_actions: User's permitted actions with constraints
          - guardrails: AI-generated rules agent MUST follow
          - metadata: Relevant policy metadata
          - warnings: Any risk flags about agent capabilities

        This context is then provided to the agent's system prompt.
        """
        pass
