"""Idempotent bootstrap — seed policies and workspace on every startup.

Replaces the standalone ``jarvis_pa/seed_policies.py`` script.  Safe to
re-run: checks for existing state before creating anything.
"""

from __future__ import annotations

import logging

from intentframe_gateway.config import GatewayConfig
from intentframe_gateway.proxy import UDSProxy

logger = logging.getLogger(__name__)

# ── Default policy seed data ─────────────────────────────────────────────────

SAFE_ACTIONS = [
    "READ_HOST_FILE", "LIST_HOST_DIRECTORY",
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
]

UNSAFE_ACTIONS = [
    "WRITE_HOST_FILE", "DELETE_HOST_FILE",
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

WORKSPACE_MOUNTS = [
    {"virtual_path": "/home/", "real_path": "~/", "writable": True},
]


def _resolve_user_id() -> str:
    from intentframe_gateway.config_loader import build_config_env
    return build_config_env().get("JARVIS_USER_ID", "jarvis_default")


def _build_default_policy() -> dict:
    allowed_actions: dict[str, dict] = {}
    # MIRROR INVARIANT (pinned by tests/test_jarvis_host_scope_mirror.py):
    # ``host_path_constraint.allowed_host_paths`` MUST mirror
    # ``jarvis_pa/executor.yaml::host_files.allowed_write_paths`` (and
    # by extension the read paths).  The executor YAML is the source
    # of truth for the adapter floor; this policy is the per-action
    # allowlist the guardian checks.  If executor.yaml narrows (e.g.
    # to ``[~/Documents/*, ~/Downloads/*]``), update this list in
    # lockstep — otherwise adapter and guardian disagree at the path
    # boundary and users see inconsistent deny reasons.
    # HostFileConstraints rejects trailing-slash shorthand (``dir/``)
    # at load time, so use explicit subtree globs only.  The disjoint
    # field name ``allowed_host_paths`` (vs ``allowed_paths``) is
    # required — it is what drives Pydantic Union-dispatch to
    # HostFileConstraints instead of FileConstraints.
    host_constraint = {"allowed_host_paths": ["~/*"]}
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
            "sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777",
        ],
    }

    for action in SAFE_ACTIONS:
        if action in ("READ_HOST_FILE", "LIST_HOST_DIRECTORY"):
            constraint = host_constraint
        else:
            constraint = None
        allowed_actions[action] = {"safe": True, "constraints": constraint}

    for action in UNSAFE_ACTIONS:
        if action in ("SEND_EMAIL", "REPLY_EMAIL", "FORWARD_EMAIL"):
            constraint = email_constraint
        elif action == "SEND_MESSAGE":
            constraint = message_constraint
        elif action in ("WRITE_HOST_FILE", "DELETE_HOST_FILE"):
            constraint = host_constraint
        elif action == "RUN_COMMAND":
            constraint = terminal_constraint
        else:
            constraint = None
        allowed_actions[action] = {"safe": False, "constraints": constraint}

    return {
        "user_id": _resolve_user_id(),
        "allowed_actions": allowed_actions,
        "intent_limits": INTENT_LIMITS,
        "metadata": {
            "profile": "jarvis-dev",
            "note": "Auto-seeded by gateway bootstrap",
        },
    }


# ── Bootstrapper ─────────────────────────────────────────────────────────────


class Bootstrapper:
    """Idempotent bootstrap: ensure policies and workspace exist."""

    async def reconcile(
        self,
        config: GatewayConfig,
        proxies: dict[str, UDSProxy],
    ) -> None:
        await self._ensure_policies(proxies)
        await self._ensure_workspace(config, proxies)

    async def _ensure_policies(self, proxies: dict[str, UDSProxy]) -> None:
        proxy = proxies.get("policy-registry")
        if proxy is None:
            logger.warning("No policy-registry proxy — skipping policy seed")
            return

        client = await proxy._get_client()

        user_id = _resolve_user_id()
        resp = await client.get(f"/policies/{user_id}")
        if resp.status_code == 200:
            logger.info("Policy %s already exists — skipping seed", user_id)
            return

        policy = _build_default_policy()
        resp = await client.post("/policies", json=policy)
        if resp.status_code in (200, 201):
            total = len(SAFE_ACTIONS) + len(UNSAFE_ACTIONS)
            logger.info(
                "Policy seeded for %s: %d actions (%d safe, %d unsafe), %d intent limits",
                user_id, total, len(SAFE_ACTIONS), len(UNSAFE_ACTIONS), len(INTENT_LIMITS),
            )
        else:
            logger.error("Failed to seed policy: %s %s", resp.status_code, resp.text)

    async def _ensure_workspace(
        self, config: GatewayConfig, proxies: dict[str, UDSProxy],
    ) -> None:
        rr_proxy = proxies.get("resource-registry")
        if rr_proxy is None:
            sock_path = config.socket_path("resource-registry.sock")
            if not sock_path.exists():
                logger.warning("No resource-registry socket — skipping workspace seed")
                return
            from intentframe_gateway.proxy import UDSProxy as _P
            rr_proxy = _P(socket_path=str(sock_path), base_url="http://resource-registry")

        client = await rr_proxy._get_client()

        user_id = _resolve_user_id()
        payload = {
            "workspace_id": user_id,
            "mounts": WORKSPACE_MOUNTS,
            "metadata": {"agent": "jarvis", "profile": "consumer"},
        }
        resp = await client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            logger.info("Workspace %s already exists — skipping seed", user_id)
        elif resp.status_code in (200, 201):
            logger.info("Workspace seeded: %d mount(s)", len(WORKSPACE_MOUNTS))
        else:
            logger.error("Failed to seed workspace: %s %s", resp.status_code, resp.text)
