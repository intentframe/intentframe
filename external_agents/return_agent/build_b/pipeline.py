"""Minimal in-process IntentFrame pipeline: Intent -> Analysis -> Guardian.

This is the hand-picked, two-component pipeline for the return-agent
experiment. It deliberately avoids the full runtime:

  - no server / supervisor
  - no executor (nothing is actually refunded)
  - no action-bundle pack / DeterministicRunner
  - no hard constraints (optional semantic intent_limits only)

It takes a single ``IntentFrame`` and runs it through the two LLM components
that matter for the guard decision:

    IntentFrame
        -> AIAnalysisEngine.analyze()   (what does this REALLY do?)
        -> AIGuardian.validate()        (ALLOW / BLOCK)

Set ``RETURN_USE_INTENT_LIMITS=1`` to attach return-domain semantic limits
to ``UserContext`` for A/B testing against the zero-policy baseline.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from intentframe_core import IntentFrame, UserContext
from intentframe_components.analysis import AIAnalysisEngine
from intentframe_components.guardian import AIGuardian
from intentframe_core.policy import SemanticIntentLimit
from intentframe_core.types import ValidationResult
from policy_registry.models import ActionPermission

from return_intent_limits import RETURN_INTENT_LIMITS

_RETURN_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_RETURN_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_RETURN_AGENT_DIR))
from terminal import intentframe  # noqa: E402

AE_MODEL = "gpt-4o-mini"
GUARDIAN_MODEL = "gpt-5-mini-2025-08-07"


def use_intent_limits_from_env() -> bool:
    return os.environ.get("RETURN_USE_INTENT_LIMITS", "").strip() in ("1", "true", "yes")


def _active_domains(user_context: UserContext) -> set[str]:
    domains: set[str] = set()
    for limit in user_context.intent_limits:
        if limit.domain:
            domains.add(limit.domain)
    domains.update(user_context.domain_constraints.keys())
    return domains


def _user_context_for(
    intent: IntentFrame,
    *,
    intent_limits: list[SemanticIntentLimit] | None = None,
) -> UserContext:
    """Allow exactly this intent's action. ``safe=False`` forces the AI path."""
    return UserContext(
        user_id=intent.authorized_by or "ops",
        agent_id=intent.agent_id or "return_agent",
        allowed_actions={intent.action: ActionPermission(safe=False)},
        intent_limits=intent_limits or [],
    )


async def process_intent_async(
    intent: IntentFrame,
    *,
    ae_model: str = AE_MODEL,
    guardian_model: str = GUARDIAN_MODEL,
    verbose: bool = True,
    use_intent_limits: bool | None = None,
) -> ValidationResult:
    """Run one intent through Analysis Engine then Guardian. Returns the verdict."""
    if use_intent_limits is None:
        use_intent_limits = use_intent_limits_from_env()

    limits = RETURN_INTENT_LIMITS if use_intent_limits else []
    analysis_engine = AIAnalysisEngine(model=ae_model, verbose=verbose)
    guardian = AIGuardian(model=guardian_model, verbose=verbose)

    user_context = _user_context_for(intent, intent_limits=limits)
    active_domains = _active_domains(user_context) if limits else None

    if verbose and limits:
        print(
            intentframe(
                f"    │  Intent limits: {len(limits)} active "
                f"domains={sorted(active_domains or [])}"
            )
        )

    report = await analysis_engine.analyze(intent, active_domains=active_domains)
    result = await guardian.validate(
        intent, report, user_context, active_domains=active_domains
    )
    return result


def process_intent(
    intent: IntentFrame,
    *,
    ae_model: str = AE_MODEL,
    guardian_model: str = GUARDIAN_MODEL,
    verbose: bool = True,
    use_intent_limits: bool | None = None,
) -> ValidationResult:
    """Synchronous wrapper around :func:`process_intent_async`."""
    return asyncio.run(
        process_intent_async(
            intent,
            ae_model=ae_model,
            guardian_model=guardian_model,
            verbose=verbose,
            use_intent_limits=use_intent_limits,
        )
    )
