"""Seed the Policy Registry and Resource Registry for Jarvis.

Run after the supervisor is up:
    python jarvis_pa/seed_policies.py

This creates:
    1. A user policy (allowed actions, intent limits)
    2. A workspace in the Resource Registry (virtual path mounts)

Profiles
--------
Seeds different policy / workspace shapes depending on the
``INTENTFRAME_PROFILE`` environment variable (mirrors
``intentframe_gateway/bootstrap.py``):

* ``user`` (default) — home-scoped host-file access (``~/*``), virtual
  workspace rooted at ``/home/``.  Mirrors ``jarvis_pa/executor.yaml``.
* ``root`` — full-filesystem host-file access (``/*``), virtual workspace
  rooted at ``/``.  Mirrors ``jarvis_pa/executor_root.yaml``.

Both profiles seed ``terminal_constraint.deny_capabilities`` with
:data:`PYTHON_SHELL_ONLY_DENY_CAPABILITIES` so ``RUN_COMMAND`` is
clamped to a python + shell language surface regardless of executor
privilege.  The corresponding constant in
``intentframe_gateway/bootstrap.py`` is the canonical source — the
two seeders historically duplicate their seed data; keep both copies
in sync.

Idempotent: checks for an existing policy before POSTing so reruns are
safe (workspace seed is idempotent on the registry's 409 response).

For development/testing only — tighten in production.
"""

from __future__ import annotations

import logging
import os
import sys

import httpx

logger = logging.getLogger(__name__)

POLICY_REGISTRY_SOCKET = "~/.intentframe/run/policy-registry.sock"
RESOURCE_REGISTRY_SOCKET = "~/.intentframe/run/resource-registry.sock"

_VALID_PROFILES = ("user", "root")


def _resolve_profile() -> str:
    """Active profile from ``INTENTFRAME_PROFILE`` (default: ``user``).

    Unknown values fall back to ``user`` so a typo never silently
    relaxes policy.
    """
    raw = (os.environ.get("INTENTFRAME_PROFILE") or "user").strip().lower()
    if raw not in _VALID_PROFILES:
        logger.warning(
            "Unknown INTENTFRAME_PROFILE=%r — falling back to 'user'", raw
        )
        return "user"
    return raw


def _resolve_user_id() -> str:
    """Base user id from ``JARVIS_USER_ID`` env (ignores profile suffix)."""
    return os.environ.get("JARVIS_USER_ID", "jarvis_default")


def _profile_user_id(profile: str) -> str:
    """User id scoped to a profile.

    Root uses a ``_root`` suffix so the two profiles' policies and
    workspaces coexist in the registry without colliding.
    """
    base = _resolve_user_id()
    return f"{base}_root" if profile == "root" else base


SAFE_ACTIONS = [
    # Host file reads
    "READ_HOST_FILE",
    "LIST_HOST_DIRECTORY",
    # User IO
    "ASK_USER",
    "SHOW_MESSAGE",
    "GET_CONFIRMATION",
    "SHOW_OPTIONS",
    # Clipboard
    "GET_CLIPBOARD",
    "SET_CLIPBOARD",
    # Search & notifications
    "SEARCH_SPOTLIGHT",
    "SHOW_NOTIFICATION",
    # Calendar (reads)
    "LIST_CALENDARS",
    "LIST_EVENTS",
    "SEARCH_EVENTS",
    # Reminders (reads)
    "LIST_REMINDER_LISTS",
    "LIST_REMINDERS",
    # Notes (reads)
    "LIST_NOTES",
    "READ_NOTE",
    # Messages (reads)
    "READ_MESSAGES",
    # Contacts (reads)
    "SEARCH_CONTACTS",
    "GET_CONTACT",
    # Browser (reads)
    "GET_PAGE_CONTENT",
    # Email (reads)
    "SEARCH_EMAIL",
    "READ_EMAIL",
    "GET_EMAIL",
    "DOWNLOAD_ATTACHMENT",
    # HTTP (reads)
    "HTTP_GET",
    # System (reads)
    "GET_SYSTEM_INFO",
    "GET_BRIGHTNESS",
    "GET_VOLUME",
    "GET_MUTE",
    "GET_DARK_MODE",
]

UNSAFE_ACTIONS = [
    # Host file writes
    "WRITE_HOST_FILE",
    "DELETE_HOST_FILE",
    # Terminal
    "RUN_COMMAND",
    # Email (writes)
    "SEND_EMAIL",
    "REPLY_EMAIL",
    "FORWARD_EMAIL",
    "MARK_READ_EMAIL",
    "MOVE_EMAIL",
    "DELETE_EMAIL",
    # Calendar (writes)
    "CREATE_EVENT",
    "UPDATE_EVENT",
    "DELETE_EVENT",
    # Reminders (writes)
    "CREATE_REMINDER",
    "UPDATE_REMINDER",
    "COMPLETE_REMINDER",
    "DELETE_REMINDER",
    # Notes (writes)
    "CREATE_NOTE",
    "DELETE_NOTE",
    # Contacts (writes)
    "ADD_CONTACT",
    "UPDATE_CONTACT",
    "DELETE_CONTACT",
    # Messages (writes)
    "SEND_MESSAGE",
    # Browser (writes)
    "OPEN_URL",
    # HTTP (writes)
    "HTTP_POST",
    "HTTP_PUT",
    "HTTP_DELETE",
    # System (writes)
    "SET_VOLUME",
    "SET_BRIGHTNESS",
    "TOGGLE_MUTE",
    "TOGGLE_DARK_MODE",
]


INTENT_LIMITS = [
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


# Capability tags denied by every profile's ``terminal_constraint``.
# Profile-independent on purpose: the language surface IntentFrame is
# willing to reason about does not change just because the executor
# happens to run as root.  Must match ``intentframe_gateway/bootstrap.py
# ::PYTHON_SHELL_ONLY_DENY_CAPABILITIES`` exactly — both seeders are
# run against the same registry and an asymmetric seed would silently
# let whichever seeder ran second relax the other's policy.  The
# contract between this set and the classifier is pinned by
# ``tests/test_python_shell_only_policy.py::TestClassifierAgreesWithPolicy``.
PYTHON_SHELL_ONLY_DENY_CAPABILITIES: frozenset[str] = frozenset({
    "capability:script_execution:node",
    "capability:script_execution:ruby",
    "capability:script_execution:perl",
    "capability:script_execution:java",
    "capability:script_execution:go",
    "capability:script_execution:dotnet",
    "capability:script_execution:php",
    "capability:script_execution:lua",
    "capability:script_execution:r",
    "capability:script_execution:julia",
    "capability:script_execution:swift",
    "capability:script_execution:deno_bun",
    # NOTE: ``awk`` is intentionally NOT denied — POSIX shell utility,
    # same risk class as sed/cut/grep which are allowed.  Policy stance
    # is: block non-python, non-shell *language runtimes*; keep POSIX
    # shell utilities.  Classifier still tags it for telemetry.
    "capability:script_execution:local_binary",
    "capability:compilation",
    "capability:stdin_exec:node",
    "capability:stdin_exec:ruby",
    "capability:stdin_exec:perl",
    "capability:stdin_exec:php",
    "capability:package_install:npm",
    "capability:package_install:gem",
    "capability:package_install:cargo",
    "capability:package_install:go",
    "capability:package_install:composer",
})


# Sensitive-surface clamp (``data_read:*`` + ``system_mutate:*``).  See
# the canonical definition in ``intentframe_gateway/bootstrap.py``
# (``SENSITIVE_SURFACE_DENY_CAPABILITIES``) — both seeders are run
# against the same registry and an asymmetric seed would silently let
# whichever seeder ran second relax the other's policy.  This clamp
# closes the root-demo attack-sweep gap (intents 36, 38, 87–91, 97,
# 99) where the AE reliably rated sensitive reads / host mutations as
# LOW/MEDIUM and Guardian allowed them; denying at Gate 2 on the
# classifier tag catches those shapes without burning an AE call.
SENSITIVE_SURFACE_DENY_CAPABILITIES: frozenset[str] = frozenset({
    # Sensitive reads (``data_read:*``).
    "capability:data_read:browser_cookies",
    "capability:data_read:browser_profile_data",
    "capability:data_read:auth_authority",
    "capability:data_read:credential_material",
    "capability:data_read:shell_history",
    "capability:data_read:messaging_history",
    "capability:data_read:personal_records",
    # System mutations (``system_mutate:*``).
    "capability:system_mutate:host_network_config",
    "capability:system_mutate:hostname",
    "capability:system_mutate:time_sync",
    "capability:system_mutate:security_daemon",
    "capability:system_mutate:browser_security_pref",
    "capability:system_mutate:firewall",
    "capability:system_mutate:hosts_file",
    "capability:system_mutate:privilege_config",
    "capability:system_mutate:user_account",
    "capability:system_mutate:remote_access",
    "capability:system_mutate:disk_encryption",
    "capability:system_mutate:kernel_tunable",
    "capability:system_mutate:persistence",
})


# Union of the two profile-independent clamps; mirrors
# ``intentframe_gateway/bootstrap.py::DEFAULT_TERMINAL_DENY_CAPABILITIES``.
DEFAULT_TERMINAL_DENY_CAPABILITIES: frozenset[str] = (
    PYTHON_SHELL_ONLY_DENY_CAPABILITIES | SENSITIVE_SURFACE_DENY_CAPABILITIES
)


def _build_policy(profile: str = "user") -> dict:
    allowed_actions: dict[str, dict] = {}
    # MIRROR INVARIANT (pinned by tests/test_jarvis_host_scope_mirror.py for
    # the user profile; the root profile mirrors
    # ``jarvis_pa/executor_root.yaml::host_files.allowed_write_paths``):
    # ``host_path_constraint.allowed_host_paths`` MUST mirror the matching
    # executor YAML's ``host_files.allowed_write_paths`` (and by extension
    # the read paths, which today are the same).  The executor YAML is
    # the source of truth; this policy is the per-action allowlist that
    # rides alongside.  If an executor.yaml narrows to e.g.
    # ``[~/Documents/*, ~/Downloads/*]``, update the matching profile
    # branch below in lockstep — otherwise the adapter and the guardian
    # will disagree at the path boundary and users see inconsistent deny
    # reasons.  HostFileConstraints rejects trailing-slash shorthand
    # (``dir/``) at load time, so use explicit subtree globs only. The
    # disjoint field name ``allowed_host_paths`` drives the Union-dispatch
    # disambiguation.
    if profile == "root":
        host_path_constraint = {"allowed_host_paths": ["/*"]}
    else:
        host_path_constraint = {"allowed_host_paths": ["~/*"]}

    for action in SAFE_ACTIONS:
        if action in ("READ_HOST_FILE", "LIST_HOST_DIRECTORY"):
            constraint = host_path_constraint
        else:
            constraint = None
        allowed_actions[action] = {
            "safe": True,
            "constraints": constraint,
        }

    email_constraint = {
        "allowed_recipients": [],
        "recipient_sources": [{"source": "contacts_all", "filter": "", "enabled": True}],
    }
    message_constraint = {
        "allowed_contacts": [],
        "contact_sources": [{"source": "contacts_all", "filter": "", "enabled": True}],
    }

    terminal_constraint = {
        "blocked_patterns": [
            "sudo",
            "rm -rf /",
            "mkfs",
            "dd if=",
            "> /dev/",
            "chmod 777",
        ],
        "deny_capabilities": sorted(DEFAULT_TERMINAL_DENY_CAPABILITIES),
    }

    for action in UNSAFE_ACTIONS:
        if action in ("SEND_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL"):
            constraint = email_constraint
        elif action == "SEND_MESSAGE":
            constraint = message_constraint
        elif action in ("WRITE_HOST_FILE", "DELETE_HOST_FILE"):
            constraint = host_path_constraint
        elif action == "RUN_COMMAND":
            constraint = terminal_constraint
        else:
            constraint = None

        allowed_actions[action] = {
            "safe": False,
            "constraints": constraint,
        }

    profile_label = "jarvis-root" if profile == "root" else "jarvis-dev"

    return {
        "user_id": _profile_user_id(profile),
        "allowed_actions": allowed_actions,
        "intent_limits": INTENT_LIMITS,
        "metadata": {
            "profile": profile_label,
            "note": "Auto-seeded by seed_policies.py",
        },
    }


WORKSPACE_MOUNTS = [
    {"virtual_path": "/home/", "real_path": "~/", "writable": True},
]

# Root-profile workspace: the virtual root coincides with the real root
# so the agent's path model matches the operator's.  Mirrors
# ``jarvis_pa/executor_root.yaml::filesystem.mounts``.
ROOT_WORKSPACE_MOUNTS = [
    {"virtual_path": "/", "real_path": "/", "writable": True},
]


def _profile_workspace_mounts(profile: str) -> list[dict]:
    return ROOT_WORKSPACE_MOUNTS if profile == "root" else WORKSPACE_MOUNTS


def _seed_workspace(socket_path: str, profile: str = "user") -> None:
    """Register Jarvis's workspace in the Resource Registry."""
    workspace_id = _profile_user_id(profile)
    mounts = _profile_workspace_mounts(profile)
    profile_label = "root" if profile == "root" else "consumer"
    transport = httpx.HTTPTransport(uds=socket_path)
    with httpx.Client(transport=transport, base_url="http://resource-registry") as client:
        payload = {
            "workspace_id": workspace_id,
            "mounts": mounts,
            "metadata": {"agent": "jarvis", "profile": profile_label},
        }
        resp = client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            print(f"Workspace {workspace_id} already exists (profile={profile}) — skipping")
            return
        resp.raise_for_status()
        print(f"Workspace seeded: {resp.json().get('workspace_id')} (profile={profile})")
        print(f"  Mounts: {len(mounts)}")
        for m in mounts:
            rw = "read/write" if m.get("writable") else "read"
            print(f"    - {m['virtual_path']} → {m['real_path']} ({rw})")


def main() -> None:
    from pathlib import Path

    policy_sock = Path(POLICY_REGISTRY_SOCKET).expanduser()
    resource_sock = Path(RESOURCE_REGISTRY_SOCKET).expanduser()

    if not policy_sock.exists():
        print(f"Error: Policy registry socket not found at {policy_sock}")
        print("Start the supervisor first: python -m supervisor.main start")
        sys.exit(1)

    profile = _resolve_profile()
    print(f"Active profile: {profile}")

    # 1. Seed policies (idempotent — GET first, POST only if absent)
    policy = _build_policy(profile)
    user_id = policy["user_id"]

    transport = httpx.HTTPTransport(uds=str(policy_sock))
    with httpx.Client(transport=transport, base_url="http://policy-registry") as client:
        existing = client.get(f"/policies/{user_id}")
        if existing.status_code == 200:
            print(f"Policy {user_id} already exists (profile={profile}) — skipping")
        else:
            resp = client.post("/policies", json=policy)
            resp.raise_for_status()
            print(f"Policy seeded: {resp.json()}")

            total = len(SAFE_ACTIONS) + len(UNSAFE_ACTIONS)
            limits = len(policy.get("intent_limits", []))
            print(f"  Allowed actions: {total} ({len(SAFE_ACTIONS)} safe, {len(UNSAFE_ACTIONS)} AI-validated)")
            print(f"  Intent limits:   {limits}")
            for lim in policy.get("intent_limits", []):
                print(f"    - [{lim['domain']}] {lim['description']} → {lim['effect']}")

    # 2. Seed workspace
    if resource_sock.exists():
        _seed_workspace(str(resource_sock), profile)
    else:
        print(f"Warning: Resource registry socket not found at {resource_sock} — workspace not seeded")


if __name__ == "__main__":
    main()
