"""Isolated onboarding run: Jarvis-seeded policy -> AIOnboardingEngine.

Exercises :class:`AIOnboardingEngine.onboard` with the *exact* policy
``intentframe_gateway.bootstrap`` seeds for Jarvis and the *exact*
``AgentCapabilities`` Jarvis declares during handshake -- without
running the gateway, executor, or any UDS proxies.

Filesystem family toggle (``--fs-mode``) filters **both**
``AgentCapabilities.action_types`` and the policy ``allowed_actions``
in lockstep so you can test onboarding for:

- VFS file actions only
- host-file actions only
- both (default, matches production bootstrap)
- neither family (all other Jarvis actions unchanged)

Not a pytest module on purpose -- runs as a plain script so you can
print the full generated ``RuntimeContext`` without pytest capture
interfering.

Requires ``OPENAI_API_KEY`` in the environment (onboarding calls the
OpenAI Agents SDK).

Run:

    python tests/test_onboarding_jarvis_policy.py
    python tests/test_onboarding_jarvis_policy.py --fs-mode vfs
    python tests/test_onboarding_jarvis_policy.py --fs-mode host
    python tests/test_onboarding_jarvis_policy.py --fs-mode none
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Literal


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

FsMode = Literal["both", "vfs", "host", "none"]

VFS_FILE_ACTIONS: frozenset[str] = frozenset({
    "READ_FILE",
    "WRITE_FILE",
    "LIST_DIRECTORY",
    "DELETE_FILE",
})

HOST_FILE_ACTIONS: frozenset[str] = frozenset({
    "READ_HOST_FILE",
    "WRITE_HOST_FILE",
    "LIST_HOST_DIRECTORY",
    "DELETE_HOST_FILE",
})

FS_FILE_ACTIONS: frozenset[str] = VFS_FILE_ACTIONS | HOST_FILE_ACTIONS


def _excluded_fs_actions(fs_mode: FsMode) -> frozenset[str]:
    if fs_mode == "both":
        return frozenset()
    if fs_mode == "vfs":
        return HOST_FILE_ACTIONS
    if fs_mode == "host":
        return VFS_FILE_ACTIONS
    if fs_mode == "none":
        return FS_FILE_ACTIONS
    raise ValueError(f"unknown fs_mode: {fs_mode!r}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AI onboarding against Jarvis bootstrap policy (no gateway).",
    )
    parser.add_argument(
        "--fs-mode",
        choices=("both", "vfs", "host", "none"),
        default="both",
        help=(
            "Which filesystem tool families to keep in both capabilities and "
            "policy: both (default), vfs only, host only, or neither."
        ),
    )
    return parser.parse_args()


def _build_jarvis_capabilities(fs_mode: FsMode) -> AgentCapabilities:
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

    excluded = _excluded_fs_actions(fs_mode)
    action_types = [a for a in _ACTION_TYPES if a not in excluded]

    cap_list = list(_CAPABILITY_LIST)
    if fs_mode == "none" and "file_ops" in cap_list:
        cap_list.remove("file_ops")

    return AgentCapabilities(
        agent_type="PersonalAssistant",
        description="Jarvis - macOS personal assistant",
        capabilities=cap_list,
        action_types=action_types,
        version="0.1.0",
        author="jarvis",
    )


def _build_jarvis_user_context(fs_mode: FsMode) -> UserContext:
    """Build a ``UserContext`` from the gateway bootstrap policy dict.

    Applies ``fs_mode`` by removing the same filesystem action keys from
    ``allowed_actions`` as :func:`_build_jarvis_capabilities` removes from
    ``action_types``.

    Goes through ``UserPolicy.model_validate`` so the raw seed dict is
    validated by the same Pydantic models the policy registry uses in
    production -- any drift in constraint schemas will fail here.
    """
    policy_dict = _build_default_policy()
    excluded = _excluded_fs_actions(fs_mode)
    raw_actions = policy_dict["allowed_actions"]
    policy_dict["allowed_actions"] = {
        action: perm for action, perm in raw_actions.items() if action not in excluded
    }
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


async def _run(
    fs_mode: FsMode,
    user_context: UserContext,
) -> RuntimeContext:
    capabilities = _build_jarvis_capabilities(fs_mode)
    execution_context = ExecutionContext()

    caps_fs = sorted(set(capabilities.action_types) & FS_FILE_ACTIONS)
    policy_fs = sorted(set(user_context.allowed_actions) & FS_FILE_ACTIONS)

    _print_header("Inputs")
    print(f"fs_mode           : {fs_mode}")
    print(f"agent_type        : {capabilities.agent_type}")
    print(f"action_types count: {len(capabilities.action_types)}")
    print(f"fs action_types   : {caps_fs}")
    print(f"user_id           : {user_context.user_id}")
    print(f"allowed_actions   : {len(user_context.allowed_actions)}")
    print(f"fs allowed_actions: {policy_fs}")
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


def _assert_sanity(
    ctx: RuntimeContext,
    user_context: UserContext,
    capabilities: AgentCapabilities,
) -> None:
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

    caps_fs = set(capabilities.action_types) & FS_FILE_ACTIONS
    policy_fs = set(user_context.allowed_actions) & FS_FILE_ACTIONS
    assert caps_fs == policy_fs, (
        "capabilities and policy disagree on filesystem actions: "
        f"capabilities={sorted(caps_fs)!r} policy={sorted(policy_fs)!r}"
    )


def main() -> int:
    args = _parse_args()
    fs_mode: FsMode = args.fs_mode  # type: ignore[assignment]

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set -- onboarding calls the OpenAI API.")
        print("Export a key and re-run, e.g.:")
        print(
            "  OPENAI_API_KEY=sk-... python tests/test_onboarding_jarvis_policy.py "
            "--fs-mode vfs"
        )
        return 2

    user_context = _build_jarvis_user_context(fs_mode)
    capabilities = _build_jarvis_capabilities(fs_mode)
    try:
        ctx = asyncio.run(_run(fs_mode, user_context))
    except Exception as exc:
        print(f"\nonboarding run failed: {exc!r}")
        return 1

    _print_runtime_context(ctx)

    try:
        _assert_sanity(ctx, user_context, capabilities)
    except AssertionError as exc:
        print(f"\nsanity check FAILED: {exc}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
