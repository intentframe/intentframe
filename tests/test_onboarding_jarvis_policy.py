"""Isolated onboarding simulation for a Jarvis-shaped agent.

Drives :class:`AIOnboardingEngine.onboard` with a **simulated** Jarvis
policy and capability set, entirely self-contained in this file.  No
imports from ``intentframe_gateway.bootstrap``, ``jarvis_pa``,
``jarvis.agent`` or any other production seed — that is intentional.

The point of the script is to exercise onboarding across all four
filesystem-family configurations regardless of what Jarvis (or any
other agent) actually ships in production:

- ``vfs``   — VFS file actions only (legacy virtual-path family)
- ``host``  — host-file actions only (real ``~/...`` paths)
- ``both``  — both families declared simultaneously
- ``none``  — neither family declared

The simulated policy is the **union** of both families plus the usual
non-filesystem Jarvis actions (email, calendar, reminders, notes,
messages, contacts, clipboard, notifications, browser, system
controls, HTTP).  ``--fs-mode`` filters this superset in lockstep
across ``AgentCapabilities.action_types`` and ``UserPolicy.allowed_actions``.

The simulated policy still goes through ``UserPolicy.model_validate``
so any drift in the registry's Pydantic models fails here.

Not a pytest module on purpose — runs as a plain script so the full
generated ``RuntimeContext`` prints without pytest output capture.

Requires ``OPENAI_API_KEY`` (onboarding calls the OpenAI Agents SDK).

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
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from intentframe_core.types import (  # noqa: E402
    AgentCapabilities,
    RuntimeContext,
    UserContext,
)
from intentframe_bundle_sdk.loader import ensure_loaded  # noqa: E402
from intentframe_components.onboarding.engine import AIOnboardingEngine  # noqa: E402
from policy_registry.models import UserPolicy  # noqa: E402

FsMode = Literal["both", "vfs", "host", "none"]

# ── Simulated filesystem families ────────────────────────────────────────────

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

_VFS_WRITE_ACTIONS: frozenset[str] = frozenset({"WRITE_FILE", "DELETE_FILE"})
_HOST_WRITE_ACTIONS: frozenset[str] = frozenset({"WRITE_HOST_FILE", "DELETE_HOST_FILE"})

# ── Simulated non-filesystem actions (superset, independent of prod) ─────────

_SAFE_NON_FS_ACTIONS: tuple[str, ...] = (
    "ASK_USER", "SHOW_MESSAGE", "GET_CONFIRMATION", "SHOW_OPTIONS",
    "GET_CLIPBOARD", "SET_CLIPBOARD",
    "SEARCH_SPOTLIGHT", "SHOW_NOTIFICATION",
    "LIST_CALENDARS", "LIST_EVENTS", "SEARCH_EVENTS",
    "LIST_REMINDER_LISTS", "LIST_REMINDERS",
    "LIST_NOTES", "READ_NOTE",
    "READ_MESSAGES",
    "SEARCH_CONTACTS", "GET_CONTACT",
    "GET_PAGE_CONTENT",
    "SEARCH_EMAIL", "READ_EMAIL", "GET_EMAIL", "DOWNLOAD_ATTACHMENT",
    "HTTP_GET",
    "GET_SYSTEM_INFO", "GET_BRIGHTNESS", "GET_VOLUME", "GET_MUTE", "GET_DARK_MODE",
)

_UNSAFE_NON_FS_ACTIONS: tuple[str, ...] = (
    "RUN_COMMAND",
    "SEND_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL",
    "MARK_READ_EMAIL", "MOVE_EMAIL", "DELETE_EMAIL",
    "CREATE_EVENT", "UPDATE_EVENT", "DELETE_EVENT",
    "CREATE_REMINDER", "UPDATE_REMINDER", "COMPLETE_REMINDER", "DELETE_REMINDER",
    "CREATE_NOTE", "DELETE_NOTE",
    "ADD_CONTACT", "UPDATE_CONTACT", "DELETE_CONTACT",
    "SEND_MESSAGE",
    "OPEN_URL",
    "HTTP_POST", "HTTP_PUT", "HTTP_DELETE",
    "SET_VOLUME", "SET_BRIGHTNESS", "TOGGLE_MUTE", "TOGGLE_DARK_MODE",
)

_SIMULATED_CAPABILITY_LIST: tuple[str, ...] = (
    "file_ops", "commands", "email", "calendar", "reminders",
    "notes", "messages", "browser", "clipboard", "spotlight",
    "notifications", "system_control",
)

_SIMULATED_INTENT_LIMITS: list[dict] = [
    {
        "limit_id": "max-spend-per-txn",
        "domain": "spending",
        "description": "Maximum $500 per transaction",
        "raw": "Don't spend more than $500 on a single thing without asking me",
        "threshold": 500.0,
        "effect": "block",
        "scope": "per_action",
    },
    {
        "limit_id": "confirm-before-delete",
        "domain": "deletion",
        "description": "Always confirm before deleting",
        "raw": "Ask me before deleting anything I can't get back",
        "effect": "require_confirmation",
        "scope": "per_action",
    },
]

# Disjoint constraint field names — validated by the matching action bundle.
_VFS_CONSTRAINT = {"allowed_paths": ["/home/*"]}
_HOST_CONSTRAINT = {"allowed_host_paths": ["~/*"]}
_EMAIL_CONSTRAINT = {
    "allowed_recipients": [],
    "recipient_sources": [{"source": "contacts_all", "filter": "", "enabled": True}],
}
_MESSAGE_CONSTRAINT = {
    "allowed_contacts": [],
    "contact_sources": [{"source": "contacts_all", "filter": "", "enabled": True}],
}
_TERMINAL_CONSTRAINT = {
    "blocked_patterns": [
        "sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777",
    ],
}


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


def _fs_action_entry(action: str) -> dict:
    """Return ``{"safe": ..., "constraints": ...}`` for a filesystem action."""
    if action in _VFS_WRITE_ACTIONS:
        return {"safe": False, "constraints": _VFS_CONSTRAINT}
    if action in VFS_FILE_ACTIONS:  # read/list
        return {"safe": True, "constraints": _VFS_CONSTRAINT}
    if action in _HOST_WRITE_ACTIONS:
        return {"safe": False, "constraints": _HOST_CONSTRAINT}
    if action in HOST_FILE_ACTIONS:  # read/list
        return {"safe": True, "constraints": _HOST_CONSTRAINT}
    raise ValueError(f"not a filesystem action: {action!r}")


def _non_fs_action_entry(action: str, *, safe: bool) -> dict:
    if action in ("SEND_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL"):
        constraint: dict | None = _EMAIL_CONSTRAINT
    elif action == "SEND_MESSAGE":
        constraint = _MESSAGE_CONSTRAINT
    elif action == "RUN_COMMAND":
        constraint = _TERMINAL_CONSTRAINT
    else:
        constraint = None
    return {"safe": safe, "constraints": constraint}


def _simulated_policy_dict(fs_mode: FsMode, *, user_id: str) -> dict:
    """Build a simulated Jarvis policy dict covering the requested fs family.

    This is the *only* source of truth for the policy in this script;
    nothing is imported from production bootstrap.
    """
    excluded = _excluded_fs_actions(fs_mode)
    allowed_actions: dict[str, dict] = {}

    for action in sorted(FS_FILE_ACTIONS):
        if action in excluded:
            continue
        allowed_actions[action] = _fs_action_entry(action)

    for action in _SAFE_NON_FS_ACTIONS:
        allowed_actions[action] = _non_fs_action_entry(action, safe=True)
    for action in _UNSAFE_NON_FS_ACTIONS:
        allowed_actions[action] = _non_fs_action_entry(action, safe=False)

    return {
        "user_id": user_id,
        "allowed_actions": allowed_actions,
        "intent_limits": _SIMULATED_INTENT_LIMITS,
        "metadata": {
            "profile": "jarvis-simulated",
            "note": "Self-contained simulation (not loaded from gateway bootstrap)",
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run AI onboarding against a simulated Jarvis-shaped policy "
            "(no gateway, no production seed)."
        ),
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
    parser.add_argument(
        "--user-id",
        default="jarvis_sim",
        help="User ID to use in the simulated policy (default: jarvis_sim).",
    )
    return parser.parse_args()


def _build_simulated_capabilities(fs_mode: FsMode) -> AgentCapabilities:
    excluded = _excluded_fs_actions(fs_mode)

    fs_actions = [a for a in sorted(FS_FILE_ACTIONS) if a not in excluded]
    non_fs_actions = list(_SAFE_NON_FS_ACTIONS) + list(_UNSAFE_NON_FS_ACTIONS)
    action_types = fs_actions + non_fs_actions

    cap_list = list(_SIMULATED_CAPABILITY_LIST)
    if fs_mode == "none" and "file_ops" in cap_list:
        cap_list.remove("file_ops")

    return AgentCapabilities(
        agent_type="PersonalAssistant",
        description="Jarvis - macOS personal assistant (simulated)",
        capabilities=cap_list,
        action_types=action_types,
        version="0.1.0",
        author="jarvis-sim",
    )


def _build_simulated_user_context(fs_mode: FsMode, user_id: str) -> UserContext:
    """Validate the simulated policy dict through the real Pydantic model."""
    policy_dict = _simulated_policy_dict(fs_mode, user_id=user_id)
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
    capabilities: AgentCapabilities,
) -> RuntimeContext:
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

    ensure_loaded(["intentframe_native_kit.intentframe_native_bundles"])
    engine = AIOnboardingEngine(verbose=True)
    return await engine.onboard(
        capabilities=capabilities,
        user_context=user_context,
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

    user_context = _build_simulated_user_context(fs_mode, args.user_id)
    capabilities = _build_simulated_capabilities(fs_mode)
    try:
        ctx = asyncio.run(_run(fs_mode, user_context, capabilities))
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
