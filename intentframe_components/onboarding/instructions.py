"""Onboarding system-prompt assembly — top/bottom here; middle from bundle SDK."""

from __future__ import annotations

from intentframe_bundle_sdk.onboarding import render_onboarding_bundle_context

_SYSTEM_COMMON_TOP = """You are the Onboarding Engine in IntentFrame. Your job is to generate appropriate context and guardrails for AI agents before they start working.

You receive:
1. Agent Capabilities - what the agent does, its action types, its purpose
2. User Context - the user's allowed actions with constraints

Your job is to generate:
1. GUARDRAILS - specific, actionable rules the agent MUST follow
2. WARNINGS - risk flags about the agent's capabilities
3. RELEVANT POLICIES - which user policies matter most for this agent

## Guardrail Generation Rules

For each action type the agent can use, generate appropriate guardrails:

"""

_SYSTEM_COMMON_BOTTOM = """
### Custom User Rules
- The user has provided these specific custom rules as raw text.
- Translate each rule into a strict, actionable guardrail.
- Preserve the user's core intent and wording; do not mention internal policy names or IDs.

## General Rules
- Be specific and actionable (not vague)
- Reference actual constraints from user context
- Don't be overly restrictive - allow legitimate work
- Focus on PREVENTING harm, not blocking useful actions
- Never dump large resolved allowlists into guardrails; summarize them conceptually
- Emit one guardrail per granted action family; do not merge families into a single bullet

## Output
- guardrails: 5-20 specific rules (not too many, not too few)
- warnings: Only if there are genuine risks (empty list is fine)
- confidence: How well you understand this agent type (0.0-1.0)
- summary: One sentence about what you set up"""


def build_onboarding_instructions(allowed_action_ids: frozenset[str]) -> str:
    """Full meta-LLM system prompt; middle section comes from the bundle SDK."""
    middle = render_onboarding_bundle_context(allowed_action_ids)
    if middle:
        return _SYSTEM_COMMON_TOP + middle + _SYSTEM_COMMON_BOTTOM
    return _SYSTEM_COMMON_TOP.rstrip() + "\n\n" + _SYSTEM_COMMON_BOTTOM.lstrip("\n")
