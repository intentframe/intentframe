"""Seed the Policy Registry and Resource Registry for Jarvis.

Run after the supervisor is up:
    python jarvis_pa/seed_policies.py

This creates:
    1. A user policy (allowed actions, intent limits)
    2. A workspace in the Resource Registry (virtual path mounts)

For development/testing only — tighten in production.
"""

from __future__ import annotations

import httpx
import sys

POLICY_REGISTRY_SOCKET = "~/.intentframe/run/policy-registry.sock"
RESOURCE_REGISTRY_SOCKET = "~/.intentframe/run/resource-registry.sock"

SAFE_ACTIONS = [
    # File reads (virtual paths)
    "READ_FILE",
    "LIST_DIRECTORY",
    # Host file reads (real paths — parallel to READ_FILE / LIST_DIRECTORY)
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
    "SEARCH_WEB",
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
    # File writes (virtual paths)
    "WRITE_FILE",
    "APPEND_ROW",
    "DELETE_FILE",
    # Host file writes (real paths — parallel to WRITE_FILE / DELETE_FILE)
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


def _build_policy() -> dict:
    allowed_actions: dict[str, dict] = {}

    home_path_constraint = {"allowed_paths": ["/home/*"]}
    # MIRROR INVARIANT (pinned by tests/test_jarvis_host_scope_mirror.py):
    # ``host_path_constraint.allowed_host_paths`` MUST mirror
    # ``jarvis_pa/executor.yaml::host_files.allowed_write_paths`` (and
    # by extension the read paths, which today are the same).  The
    # executor YAML is the source of truth; this policy is the
    # per-action allowlist that rides alongside.  If executor.yaml
    # ever narrows to e.g. ``[~/Documents/*, ~/Downloads/*]``, update
    # the list below in lockstep — otherwise the adapter and the
    # guardian will disagree at the path boundary and users see
    # inconsistent deny reasons.  HostFileConstraints rejects
    # trailing-slash shorthand (``dir/``) at load time, so use
    # explicit subtree globs only.  Disjoint field name
    # (``allowed_host_paths``) vs ``home_path_constraint.allowed_paths``
    # drives the Union-dispatch disambiguation — keep them distinct.
    host_path_constraint = {"allowed_host_paths": ["~/*"]}

    for action in SAFE_ACTIONS:
        if action in ("READ_FILE", "LIST_DIRECTORY"):
            constraint = home_path_constraint
        elif action in ("READ_HOST_FILE", "LIST_HOST_DIRECTORY"):
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
    }

    for action in UNSAFE_ACTIONS:
        if action in ("SEND_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL"):
            constraint = email_constraint
        elif action == "SEND_MESSAGE":
            constraint = message_constraint
        elif action in ("WRITE_FILE", "DELETE_FILE"):
            constraint = home_path_constraint
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

    intent_limits = [
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

    return {
        "user_id": "jarvis_default",
        "allowed_actions": allowed_actions,
        "intent_limits": intent_limits,
        "metadata": {
            "profile": "jarvis-dev",
            "note": "Auto-seeded by seed_policies.py",
        },
    }


WORKSPACE_MOUNTS = [
    {"virtual_path": "/home/", "real_path": "~/", "writable": True},
]


def _seed_workspace(socket_path: str) -> None:
    """Register Jarvis's workspace in the Resource Registry."""
    transport = httpx.HTTPTransport(uds=socket_path)
    with httpx.Client(transport=transport, base_url="http://resource-registry") as client:
        payload = {
            "workspace_id": "jarvis_default",
            "mounts": WORKSPACE_MOUNTS,
            "metadata": {"agent": "jarvis", "profile": "consumer"},
        }
        resp = client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            print("Workspace already exists — skipping")
            return
        resp.raise_for_status()
        print(f"Workspace seeded: {resp.json().get('workspace_id')}")
        print(f"  Mounts: {len(WORKSPACE_MOUNTS)}")
        for m in WORKSPACE_MOUNTS:
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

    # 1. Seed policies
    policy = _build_policy()

    transport = httpx.HTTPTransport(uds=str(policy_sock))
    with httpx.Client(transport=transport, base_url="http://policy-registry") as client:
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
        _seed_workspace(str(resource_sock))
    else:
        print(f"Warning: Resource registry socket not found at {resource_sock} — workspace not seeded")


if __name__ == "__main__":
    main()
