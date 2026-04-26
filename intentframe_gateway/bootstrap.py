"""Idempotent bootstrap — seed policies and workspace on every startup.

Replaces the standalone ``jarvis_pa/seed_policies.py`` script.  Safe to
re-run: checks for existing state before creating anything.

Profiles
--------
The gateway seeds different policy / workspace shapes depending on the
``INTENTFRAME_PROFILE`` environment variable:

* ``user`` (default) — home-scoped host-file access (``~/*``), virtual
  workspace rooted at ``/home/``.  Mirrors ``jarvis_pa/executor.yaml``.
* ``root`` — full-filesystem host-file access (``/*``), virtual workspace
  rooted at ``/``.  Mirrors ``jarvis_pa/executor_root.yaml``.

The profile only changes three values (host constraint, workspace
mount, policy user id + metadata label).  Everything else (SAFE/UNSAFE
action sets, terminal ``blocked_patterns``, terminal
``deny_capabilities``, email/message constraints, intent limits, and
the gateway's non-negotiable floor enforced by
``resource_registry/floor.py``) is intentionally identical across
profiles — the root profile still blocks ``sudo`` because the demo
claim is "already root, no need to escalate", and both profiles
clamp ``RUN_COMMAND`` to a python + shell language surface via
:data:`PYTHON_SHELL_ONLY_DENY_CAPABILITIES`.  The shared deny-set is
the design stance: the language surface IntentFrame is willing to
reason about does not depend on whether the executor happens to run
as root.

``_build_default_policy`` is a stable alias for the user profile so the
``tests/test_jarvis_host_scope_mirror.py`` mirror invariant against
``jarvis_pa/executor.yaml`` stays pinned.
"""

from __future__ import annotations

import logging
import os

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

# Capability tags denied by every profile's ``terminal_constraint``.
# The set encodes a "python + shell only" language surface: every other
# scripting interpreter, build/link toolchain, and non-pip/non-shell
# package install is rejected at Gate 2 (DeterministicGuardian) before
# any LLM cost.  This is profile-independent on purpose — the language
# surface IntentFrame is willing to reason about does not change just
# because the executor happens to run as root.  Tag suffixes mirror
# what ``command_shield.classifier._SCRIPT_EXECUTION_RULES`` actually
# emits; the contract is pinned by
# ``tests/test_python_shell_only_policy.py::TestClassifierAgreesWithPolicy``.
#
# Mirror invariant: ``jarvis_pa/seed_policies.py`` defines the same
# constant inline (the two seeders historically duplicate their seed
# data — see ``SAFE_ACTIONS`` / ``UNSAFE_ACTIONS``).  Keep both copies
# in sync; ``demo/tests/root_demo/test_policy_root.yaml`` mirrors the
# values literally as well.
PYTHON_SHELL_ONLY_DENY_CAPABILITIES: frozenset[str] = frozenset({
    # Script execution — every non-python/shell interpreter the
    # classifier knows about (file form + inline-eval form share a
    # single tag per language).
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
    # NOTE: ``awk`` is intentionally NOT denied — it is a POSIX shell
    # utility (IEEE Std 1003.1), part of the canonical Unix toolchain
    # every model is heavily trained on, and structurally in the same
    # bucket as ``sed`` / ``cut`` / ``tr`` / ``grep`` which are allowed.
    # The policy stance is: block non-python, non-shell *language
    # runtimes*; keep all POSIX shell utilities.  The classifier still
    # emits ``capability:script_execution:awk`` for telemetry so this
    # decision stays one edit away.
    # Direct execution of compiled local binaries (``./foo``,
    # ``./bin/tool``).  Source compilation is below.
    "capability:script_execution:local_binary",
    # Build / link toolchains (gcc / clang / make / cargo build /
    # go build / rustc / javac / …).
    "capability:compilation",
    # Stdin-piped exec into non-python/shell interpreters.
    # ``cat foo.js | node`` was previously slipping through with only
    # the binary ``capability:stdin_exec`` tag; the classifier now
    # emits a per-interpreter suffix so the policy can deny
    # ``stdin_exec:node`` while still allowing
    # ``stdin_exec:python`` / ``stdin_exec:shell`` (legitimate uses
    # like ``echo 'print(1)' | python``).
    "capability:stdin_exec:node",
    "capability:stdin_exec:ruby",
    "capability:stdin_exec:perl",
    "capability:stdin_exec:php",
    # Non-python/non-shell ecosystem package installs.  pip / brew /
    # apt / yum / dnf / pacman / apk / gem-via-bundler are intentionally
    # absent — those count as part of the python or shell ecosystem.
    "capability:package_install:npm",
    "capability:package_install:gem",
    "capability:package_install:cargo",
    "capability:package_install:go",
    "capability:package_install:composer",
})


WORKSPACE_MOUNTS = [
    {"virtual_path": "/home/", "real_path": "~/", "writable": True},
]

# Root-profile workspace: the virtual root coincides with the real root
# so the agent's path model matches the operator's.  Mirrors
# ``jarvis_pa/executor_root.yaml::filesystem.mounts``.
ROOT_WORKSPACE_MOUNTS = [
    {"virtual_path": "/", "real_path": "/", "writable": True},
]

_VALID_PROFILES = ("user", "root")


def _resolve_profile() -> str:
    """Active profile from ``INTENTFRAME_PROFILE`` (default: ``user``).

    Unknown values fall back to ``user`` with a warning so a typo never
    silently relaxes policy.
    """
    raw = (os.environ.get("INTENTFRAME_PROFILE") or "user").strip().lower()
    if raw not in _VALID_PROFILES:
        logger.warning(
            "Unknown INTENTFRAME_PROFILE=%r — falling back to 'user'", raw
        )
        return "user"
    return raw


def _resolve_user_id() -> str:
    """Base user id from system config (ignores profile suffix)."""
    from intentframe_gateway.config_loader import build_config_env
    return build_config_env().get("JARVIS_USER_ID", "jarvis_default")


def _profile_user_id(profile: str) -> str:
    """User id scoped to a profile.

    Root uses a ``_root`` suffix so the two profiles' policies and
    workspaces coexist in the registry without colliding.
    """
    base = _resolve_user_id()
    return f"{base}_root" if profile == "root" else base


def policy_user_id_for_current_profile() -> str:
    """``user_id`` value used in policy-registry for the active :envvar:`INTENTFRAME_PROFILE`.

    Child processes (Jarvis, etc.) must receive this as :envvar:`JARVIS_USER_ID`
    so their runtime identity matches the record :class:`Bootstrapper` seeds
    in policy-registry.  Without that alignment, the core load shows
    "No policy for user …" and unsafe defaults (e.g. no allowed actions).
    """
    return _profile_user_id(_resolve_profile())


def _profile_workspace_mounts(profile: str) -> list[dict]:
    return ROOT_WORKSPACE_MOUNTS if profile == "root" else WORKSPACE_MOUNTS


def _build_policy(profile: str = "user") -> dict:
    """Build a seeded policy for the given profile.

    Profiles differ only in three values:
      * ``host_constraint.allowed_host_paths`` — ``~/*`` (user) vs ``/*``
        (root).  Mirrors the matching executor YAML's
        ``host_files.allowed_{read,write}_paths``.
      * ``user_id`` — profile-suffixed (see :func:`_profile_user_id`).
      * ``metadata.profile`` — label for audit visibility.

    Everything else — SAFE/UNSAFE sets, terminal ``blocked_patterns``,
    terminal ``deny_capabilities`` (python + shell language clamp),
    email/message constraints, intent limits — is intentionally shared.
    The root profile deliberately keeps ``sudo`` in ``blocked_patterns``
    because the demo stance is "executor already runs as root; agents
    must not attempt privilege escalation".
    """
    allowed_actions: dict[str, dict] = {}

    # MIRROR INVARIANT (pinned by tests/test_jarvis_host_scope_mirror.py
    # for the user profile; the root profile mirrors
    # ``jarvis_pa/executor_root.yaml::host_files.allowed_write_paths``).
    # ``host_path_constraint.allowed_host_paths`` MUST mirror the matching
    # executor YAML's ``host_files.allowed_write_paths`` (and by extension
    # the read paths).  The executor YAML is the source of truth for the
    # adapter floor; this policy is the per-action allowlist the guardian
    # checks.  If an executor.yaml narrows (e.g. to
    # ``[~/Documents/*, ~/Downloads/*]``), update the matching profile
    # branch here in lockstep — otherwise adapter and guardian disagree at
    # the path boundary and users see inconsistent deny reasons.
    # HostFileConstraints rejects trailing-slash shorthand (``dir/``) at
    # load time, so use explicit subtree globs only.  The disjoint field
    # name ``allowed_host_paths`` (vs ``allowed_paths``) is required — it
    # is what drives Pydantic Union-dispatch to HostFileConstraints
    # instead of FileConstraints.
    if profile == "root":
        host_constraint = {"allowed_host_paths": ["/*"]}
    else:
        host_constraint = {"allowed_host_paths": ["~/*"]}

    email_constraint = {
        "allowed_recipients": [],
        "recipient_sources": [{"source": "contacts_all", "filter": "", "enabled": True}],
    }
    message_constraint = {
        "allowed_contacts": [],
        "contact_sources": [{"source": "contacts_all", "filter": "", "enabled": True}],
    }
    # Both profiles get the same RUN_COMMAND clamp: python + shell is
    # the entire language surface IntentFrame is willing to deterministically
    # reason about, regardless of executor privilege.  Sorted for stable
    # JSON-payload ordering across reseeds — Pydantic coerces back to
    # ``frozenset`` on the registry side.
    terminal_constraint = {
        "blocked_patterns": [
            "sudo", "rm -rf /", "mkfs", "dd if=", "> /dev/", "chmod 777",
        ],
        "deny_capabilities": sorted(PYTHON_SHELL_ONLY_DENY_CAPABILITIES),
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

    profile_label = "jarvis-root" if profile == "root" else "jarvis-dev"

    return {
        "user_id": _profile_user_id(profile),
        "allowed_actions": allowed_actions,
        "intent_limits": INTENT_LIMITS,
        "metadata": {
            "profile": profile_label,
            "note": "Auto-seeded by gateway bootstrap",
        },
    }


def _build_default_policy() -> dict:
    """Backwards-compatible alias for the user-profile policy.

    Intentionally env-independent: ``tests/test_jarvis_host_scope_mirror.py``
    calls this directly to pin the ``jarvis_pa/executor.yaml`` ↔ policy
    mirror, so its return value must not change under
    ``INTENTFRAME_PROFILE=root``.
    """
    return _build_policy("user")


def _build_root_policy() -> dict:
    """Root-profile seeded policy (host-file scope ``/*``)."""
    return _build_policy("root")


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

        profile = _resolve_profile()
        user_id = _profile_user_id(profile)
        resp = await client.get(f"/policies/{user_id}")
        if resp.status_code == 200:
            logger.info(
                "Policy %s already exists (profile=%s) — skipping seed",
                user_id, profile,
            )
            return

        policy = _build_policy(profile)
        resp = await client.post("/policies", json=policy)
        if resp.status_code in (200, 201):
            total = len(SAFE_ACTIONS) + len(UNSAFE_ACTIONS)
            logger.info(
                "Policy seeded for %s (profile=%s): %d actions (%d safe, %d unsafe), %d intent limits",
                user_id, profile, total, len(SAFE_ACTIONS), len(UNSAFE_ACTIONS), len(INTENT_LIMITS),
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

        profile = _resolve_profile()
        user_id = _profile_user_id(profile)
        mounts = _profile_workspace_mounts(profile)
        profile_label = "root" if profile == "root" else "consumer"
        payload = {
            "workspace_id": user_id,
            "mounts": mounts,
            "metadata": {"agent": "jarvis", "profile": profile_label},
        }
        resp = await client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            logger.info(
                "Workspace %s already exists (profile=%s) — skipping seed",
                user_id, profile,
            )
        elif resp.status_code in (200, 201):
            logger.info(
                "Workspace seeded (profile=%s): %d mount(s)",
                profile, len(mounts),
            )
        else:
            logger.error("Failed to seed workspace: %s %s", resp.status_code, resp.text)
