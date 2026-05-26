#!/usr/bin/env python3
"""
Inspect onboarding prompts — prints the EXACT system + user prompts the
Onboarding Engine would send to the meta-LLM, using a mock UserContext
loaded from the packaged Jarvis policy YAML (no LLM, no API key).

Run:

    .venv/bin/python tests/inspect_onboarding_prompts.py

Write split parity fixtures for future golden checks:

    .venv/bin/python tests/inspect_onboarding_prompts.py --write-baseline
"""

from __future__ import annotations

import argparse
import sys
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intentframe_core.types import (  # noqa: E402
    AgentCapabilities,
    ExecutionContext,
    UserContext,
)
from intentframe_components.onboarding.engine import AIOnboardingEngine  # noqa: E402
from intentframe_server.runtime_context_for_llms import (  # noqa: E402
    SubstrateContext,
    onboarding_runtime_context_for_llm,
)
from policy_registry.seeds.loader import load_policy_seed  # noqa: E402
from tests._bundle_loader import ensure_test_bundles_loaded  # noqa: E402
from tests.onboarding_prompt_parity import (  # noqa: E402
    FIXTURES_DIR,
    split_system_prompt,
    write_parity_fixtures,
)

SEPARATOR = "═" * 72
JARVIS_POLICY_YAML = REPO_ROOT / "jarvis_pa" / "jarvis" / "policies" / "jarvis.yaml"

# Mirrors ``jarvis_pa/jarvis/agent.py`` — kept here so inspect stays
# self-contained and does not import jarvis_pa.
_JARVIS_CAPABILITY_LIST: tuple[str, ...] = (
    "file_ops",
    "commands",
    "email",
    "calendar",
    "reminders",
    "notes",
    "messages",
    "browser",
    "clipboard",
    "spotlight",
    "notifications",
    "system_control",
)

_JARVIS_ACTION_TYPES: tuple[str, ...] = (
    "READ_HOST_FILE",
    "WRITE_HOST_FILE",
    "LIST_HOST_DIRECTORY",
    "DELETE_HOST_FILE",
    "RUN_COMMAND",
    "SEND_EMAIL",
    "READ_EMAIL",
    "SEARCH_EMAIL",
    "GET_EMAIL",
    "REPLY_EMAIL",
    "FORWARD_EMAIL",
    "MARK_READ_EMAIL",
    "MOVE_EMAIL",
    "DELETE_EMAIL",
    "DOWNLOAD_ATTACHMENT",
    "CREATE_EVENT",
    "LIST_EVENTS",
    "LIST_CALENDARS",
    "UPDATE_EVENT",
    "DELETE_EVENT",
    "SEARCH_EVENTS",
    "CREATE_REMINDER",
    "LIST_REMINDERS",
    "LIST_REMINDER_LISTS",
    "COMPLETE_REMINDER",
    "UPDATE_REMINDER",
    "DELETE_REMINDER",
    "CREATE_NOTE",
    "LIST_NOTES",
    "READ_NOTE",
    "DELETE_NOTE",
    "SEND_MESSAGE",
    "READ_MESSAGES",
    "SEARCH_CONTACTS",
    "GET_CONTACT",
    "ADD_CONTACT",
    "UPDATE_CONTACT",
    "DELETE_CONTACT",
    "OPEN_URL",
    "GET_PAGE_CONTENT",
    "GET_CLIPBOARD",
    "SET_CLIPBOARD",
    "SEARCH_SPOTLIGHT",
    "SHOW_NOTIFICATION",
    "ASK_USER",
    "GET_SYSTEM_INFO",
    "SET_VOLUME",
    "GET_VOLUME",
    "TOGGLE_MUTE",
    "GET_MUTE",
    "SET_BRIGHTNESS",
    "GET_BRIGHTNESS",
    "TOGGLE_DARK_MODE",
    "GET_DARK_MODE",
    "HTTP_GET",
    "HTTP_POST",
    "HTTP_PUT",
    "HTTP_DELETE",
)


def build_jarvis_user_context(
    *,
    policy_path: Path | None = None,
    user_id: str = "demo-user",
    agent_id: str = "jarvis",
) -> UserContext:
    """Mock ``UserContext`` from the packaged Jarvis policy YAML seed."""
    ensure_test_bundles_loaded()
    policy = load_policy_seed(
        policy_path or JARVIS_POLICY_YAML,
        user_id=user_id,
        agent_id=agent_id,
    )
    return UserContext(
        user_id=policy.user_id,
        agent_id=policy.agent_id,
        allowed_actions=policy.allowed_actions,
        intent_limits=policy.intent_limits,
        domain_constraints=policy.domain_constraints,
        metadata=policy.metadata,
    )


def build_jarvis_capabilities() -> AgentCapabilities:
    """``AgentCapabilities`` aligned with production Jarvis handshake."""
    return AgentCapabilities(
        agent_type="PersonalAssistant",
        description="Jarvis – macOS personal assistant",
        capabilities=list(_JARVIS_CAPABILITY_LIST),
        action_types=list(_JARVIS_ACTION_TYPES),
        version="0.1.0",
        author="jarvis",
    )


async def build_onboarding_prompts(
    *,
    user_context: UserContext,
    capabilities: AgentCapabilities,
    executor_running_as_root: bool = False,
) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` without calling the LLM."""
    engine = AIOnboardingEngine(verbose=False)
    execution = ExecutionContext(executor_running_as_root=executor_running_as_root)
    runtime_context = onboarding_runtime_context_for_llm(
        (SubstrateContext(execution=execution),),
    )
    allowed_action_ids = frozenset(user_context.allowed_actions.keys())
    system_prompt = AIOnboardingEngine._build_instructions(allowed_action_ids)
    user_prompt = await engine._build_onboarding_prompt(
        capabilities,
        user_context,
        runtime_context_for_llm=runtime_context,
    )
    return system_prompt, user_prompt


def section(title: str, out: StringIO) -> None:
    out.write(f"\n{SEPARATOR}\n")
    out.write(f"  {title}\n")
    out.write(f"{SEPARATOR}\n")


async def render_inspection(
    *,
    user_context: UserContext,
    capabilities: AgentCapabilities,
    executor_running_as_root: bool = False,
) -> str:
    """Full inspect output (split system parts + user prompt)."""
    system_prompt, user_prompt = await build_onboarding_prompts(
        user_context=user_context,
        capabilities=capabilities,
        executor_running_as_root=executor_running_as_root,
    )
    allowed_action_ids = frozenset(user_context.allowed_actions.keys())
    common_top, middle, common_bottom = split_system_prompt(system_prompt, allowed_action_ids)
    buf = StringIO()

    section("1a. ONBOARDING — SYSTEM COMMON TOP", buf)
    buf.write("\n")
    buf.write(common_top)
    buf.write("\n")

    section("1b. ONBOARDING — SYSTEM BUNDLE SECTIONS (middle)", buf)
    buf.write("\n")
    buf.write(middle)
    buf.write("\n")

    section("1c. ONBOARDING — SYSTEM COMMON BOTTOM", buf)
    buf.write("\n")
    buf.write(common_bottom)
    buf.write("\n")

    section("2. ONBOARDING — USER PROMPT (_build_onboarding_prompt)", buf)
    buf.write("\n")
    buf.write(user_prompt)
    buf.write("\n")

    constrained = sum(
        1 for perm in user_context.allowed_actions.values() if perm.constraints is not None
    )
    section("INFO (not parity-gated)", buf)
    buf.write("\n")
    buf.write(f"  policy source          : {JARVIS_POLICY_YAML.relative_to(REPO_ROOT)}\n")
    buf.write(f"  user_id                : {user_context.user_id}\n")
    buf.write(f"  agent_id               : {user_context.agent_id}\n")
    buf.write(f"  allowed_actions        : {len(user_context.allowed_actions)}\n")
    buf.write(f"  constrained actions    : {constrained}\n")
    buf.write(f"  intent_limits          : {len(user_context.intent_limits)}\n")
    buf.write(f"  executor_running_as_root: {executor_running_as_root}\n")
    buf.write(f"  system prompt chars    : {len(system_prompt):,}\n")
    buf.write(f"  user prompt chars      : {len(user_prompt):,}\n")
    buf.write("\n")

    return buf.getvalue()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Print exact onboarding system + user prompts for a Jarvis-shaped "
            "mock UserContext loaded from jarvis.yaml."
        ),
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"Write split parity fixtures under {FIXTURES_DIR.relative_to(REPO_ROOT)}/",
    )
    parser.add_argument(
        "--root",
        action="store_true",
        help="Include root executor substrate section in the user prompt.",
    )
    parser.add_argument(
        "--user-id",
        default="demo-user",
        help="user_id injected when loading the policy seed (default: demo-user).",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    user_context = build_jarvis_user_context(user_id=args.user_id)
    capabilities = build_jarvis_capabilities()
    output = await render_inspection(
        user_context=user_context,
        capabilities=capabilities,
        executor_running_as_root=args.root,
    )

    if args.write_baseline:
        system_prompt, user_prompt = await build_onboarding_prompts(
            user_context=user_context,
            capabilities=capabilities,
            executor_running_as_root=args.root,
        )
        write_parity_fixtures(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            allowed_action_ids=frozenset(user_context.allowed_actions.keys()),
        )
        print(f"Wrote parity fixtures → {FIXTURES_DIR.relative_to(REPO_ROOT)}/")
        return 0

    print(output, end="")
    return 0


if __name__ == "__main__":
    import asyncio as _asyncio
    raise SystemExit(_asyncio.run(main()))
