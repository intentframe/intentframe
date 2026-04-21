"""Isolated onboarding run: Jarvis-seeded policy -> AIOnboardingEngine.

Exercises :class:`AIOnboardingEngine.onboard` with the *exact* policy
``intentframe_gateway.bootstrap`` seeds for Jarvis and the *exact*
``AgentCapabilities`` Jarvis declares during handshake -- without
running the gateway, executor, or any UDS proxies.

Intended use:

- Iterate on onboarding prompt wording and see the guardrails the
  runtime emits for a real product policy.
- Sanity-check that the schema round-trips (policy dict -> UserPolicy
  -> UserContext) for the Jarvis action set.

Not a pytest module on purpose -- runs as a plain script so you can
print the full generated ``RuntimeContext`` without pytest capture
interfering.

Requires ``OPENAI_API_KEY`` in the environment (onboarding calls the
OpenAI Agents SDK).

Run:

    python tests/test_onboarding_jarvis_policy.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_JARVIS_PA = _REPO_ROOT / "jarvis_pa"
for extra in (_REPO_ROOT, _JARVIS_PA):
    extra_str = str(extra)
    if extra_str not in sys.path:
        sys.path.insert(0, extra_str)


from intentframe_core.types import (  # noqa: E402
    AgentCapabilities,
    ExecutionContext,
    RuntimeContext,
    UserContext,
)
from intentframe_components.onboarding.engine import AIOnboardingEngine  # noqa: E402
from intentframe_gateway.bootstrap import _build_default_policy  # noqa: E402
from policy_registry.models import UserPolicy  # noqa: E402


def _build_jarvis_capabilities() -> AgentCapabilities:
    """Mirror of the capabilities block in ``jarvis_pa/jarvis/agent.py``.

    Imported lazily so the script still runs even if ``jarvis_pa`` is
    not installed as a package in the current environment -- we fall
    back to a hardcoded copy if the import fails.
    """
    try:
        from jarvis.agent import _ACTION_TYPES, _CAPABILITY_LIST  # type: ignore
    except Exception:
        _CAPABILITY_LIST = [
            "file_ops", "commands", "email", "calendar", "reminders",
            "notes", "messages", "browser", "clipboard", "spotlight",
            "notifications", "system_control",
        ]
        _ACTION_TYPES = [
            "READ_FILE", "WRITE_FILE", "LIST_DIRECTORY", "DELETE_FILE",
            "READ_HOST_FILE", "WRITE_HOST_FILE", "LIST_HOST_DIRECTORY", "DELETE_HOST_FILE",
            "RUN_COMMAND",
            "SEND_EMAIL", "READ_EMAIL", "SEARCH_EMAIL",
            "GET_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL", "MARK_READ_EMAIL",
            "MOVE_EMAIL", "DELETE_EMAIL", "DOWNLOAD_ATTACHMENT",
            "CREATE_EVENT", "LIST_EVENTS", "LIST_CALENDARS", "UPDATE_EVENT",
            "DELETE_EVENT", "SEARCH_EVENTS",
            "CREATE_REMINDER", "LIST_REMINDERS", "LIST_REMINDER_LISTS",
            "COMPLETE_REMINDER", "UPDATE_REMINDER", "DELETE_REMINDER",
            "CREATE_NOTE", "LIST_NOTES", "READ_NOTE", "DELETE_NOTE",
            "SEND_MESSAGE", "READ_MESSAGES",
            "SEARCH_CONTACTS", "GET_CONTACT", "ADD_CONTACT",
            "UPDATE_CONTACT", "DELETE_CONTACT",
            "OPEN_URL", "SEARCH_WEB", "GET_PAGE_CONTENT",
            "GET_CLIPBOARD", "SET_CLIPBOARD",
            "SEARCH_SPOTLIGHT", "SHOW_NOTIFICATION", "ASK_USER",
            "GET_SYSTEM_INFO", "SET_VOLUME", "SET_BRIGHTNESS", "TOGGLE_DARK_MODE",
        ]

    return AgentCapabilities(
        agent_type="PersonalAssistant",
        description="Jarvis - macOS personal assistant",
        capabilities=list(_CAPABILITY_LIST),
        action_types=list(_ACTION_TYPES),
        version="0.1.0",
        author="jarvis",
    )


def _build_jarvis_user_context() -> UserContext:
    """Build a ``UserContext`` from the gateway bootstrap policy dict.

    Goes through ``UserPolicy.model_validate`` so the raw seed dict is
    validated by the same Pydantic models the policy registry uses in
    production -- any drift in constraint schemas will fail here.
    """
    policy_dict = _build_default_policy()
    policy = UserPolicy.model_validate(policy_dict)
    return UserContext(
        user_id=policy.user_id,
        allowed_actions=policy.allowed_actions,
        intent_limits=policy.intent_limits,
        domain_constraints=policy.domain_constraints,
        metadata=policy.metadata,
    )


def _print_header(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n{title}\n{bar}")


def _print_runtime_context(ctx: RuntimeContext) -> None:
    _print_header("RuntimeContext")
    print(f"user_id              : {ctx.user_id}")
    print(f"onboarded_agent_type : {ctx.onboarded_agent_type}")
    print(f"onboarding_confidence: {ctx.onboarding_confidence:.2f}")
    print(f"available_actions    : {len(ctx.available_actions)} action types")

    _print_header(f"Guardrails ({len(ctx.guardrails)})")
    for i, rule in enumerate(ctx.guardrails, 1):
        print(f"  {i}. {rule}")

    _print_header(f"Warnings ({len(ctx.warnings)})")
    if ctx.warnings:
        for w in ctx.warnings:
            print(f"  - {w}")
    else:
        print("  (none)")


async def _run() -> RuntimeContext:
    capabilities = _build_jarvis_capabilities()
    user_context = _build_jarvis_user_context()
    execution_context = ExecutionContext()

    _print_header("Inputs")
    print(f"agent_type        : {capabilities.agent_type}")
    print(f"action_types count: {len(capabilities.action_types)}")
    print(f"user_id           : {user_context.user_id}")
    print(f"allowed_actions   : {len(user_context.allowed_actions)}")
    constrained = sum(
        1 for p in user_context.allowed_actions.values() if p.constraints is not None
    )
    print(f"constrained       : {constrained}")

    engine = AIOnboardingEngine(verbose=True)
    return await engine.onboard(
        capabilities=capabilities,
        user_context=user_context,
        execution_context=execution_context,
    )


def _assert_sanity(ctx: RuntimeContext, user_context: UserContext) -> None:
    """Light invariants so the script exits non-zero on obvious regressions."""
    assert ctx.user_id == user_context.user_id, (
        f"user_id mismatch: {ctx.user_id!r} vs {user_context.user_id!r}"
    )
    assert ctx.onboarded_agent_type == "PersonalAssistant", (
        f"unexpected onboarded_agent_type: {ctx.onboarded_agent_type!r}"
    )
    assert ctx.guardrails, "onboarding emitted zero guardrails"
    assert 0.0 <= ctx.onboarding_confidence <= 1.0, (
        f"confidence out of range: {ctx.onboarding_confidence}"
    )


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set -- onboarding calls the OpenAI API.")
        print("Export a key and re-run, e.g.:")
        print("  OPENAI_API_KEY=sk-... python tests/test_onboarding_jarvis_policy.py")
        return 2

    user_context = _build_jarvis_user_context()
    try:
        ctx = asyncio.run(_run())
    except Exception as exc:
        print(f"\nonboarding run failed: {exc!r}")
        return 1

    _print_runtime_context(ctx)

    try:
        _assert_sanity(ctx, user_context)
    except AssertionError as exc:
        print(f"\nsanity check FAILED: {exc}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
