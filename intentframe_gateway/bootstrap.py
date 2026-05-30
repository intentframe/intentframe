"""Idempotent bootstrap — seed the Jarvis policy and workspace on every gateway startup.

Policy data lives in YAML inside the Jarvis package
(``jarvis/policies/jarvis.yaml`` for user-mode and
``jarvis/policies/jarvis_root.yaml`` for root-mode) and is loaded via
:func:`policy_registry.seeds.load_policy_seed`.  This module is
responsible for orchestration only:

* Resolving which Jarvis variant to run (``JARVIS_VARIANT`` env var,
  default ``user``).
* Resolving the operator/owner ``user_id`` (``identity.user_id`` from
  ``~/.intentframe/gateway.yaml`` via :mod:`intentframe_gateway.config_loader`,
  with the same env fallback as the rest of IntentFrame).
* Looking up the right ``agent_id`` for that variant (``jarvis`` or
  ``jarvis_root``).
* Honouring ``~/.intentframe/policies/<agent_id>.yaml`` overrides via
  :func:`policy_registry.seeds.resolve_seed_path`.
* Talking to the policy- and resource-registry sockets to seed both
  records idempotently (GET-first, skip if present).

Identity model
--------------
The gateway only auto-seeds Jarvis.  External agents register their
own policies via the CLI / their own installer; that path is intentionally
not handled here.  The registry stores policies keyed on the
``(user_id, agent_id)`` pair, so external agents and Jarvis never
collide even when they share the same ``user_id``.

Variants
--------
* ``user`` (default) — home-scoped host-file access (``~/*``), virtual
  workspace rooted at ``/home/``.  Mirrors ``jarvis_pa/executor.yaml``.
* ``root`` — full-filesystem host-file access (``/*``), virtual
  workspace rooted at ``/``.  Mirrors ``jarvis_pa/executor_root.yaml``.

Customisation
-------------
End users can override either packaged variant by dropping a YAML file
at ``~/.intentframe/policies/<agent_id>.yaml`` (e.g.
``~/.intentframe/policies/jarvis.yaml``).  Restart the gateway and the
override seeds on next bootstrap; the packaged builtin is never modified
by the runtime.

Public surface (used elsewhere in the codebase / docs)
------------------------------------------------------
* :data:`SAFE_ACTIONS`, :data:`UNSAFE_ACTIONS`, :data:`INTENT_LIMITS`
* :func:`_build_default_policy`, :func:`_build_jarvis_policy`
* :func:`current_jarvis_identity` — returns ``(user_id, agent_id)``
  for the active variant; child processes (Jarvis, Telegram bridge)
  read this so their runtime identity matches the seeded policy slot.
* :class:`Bootstrapper`
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from jarvis.policies import (
    JARVIS_AGENT_IDS,
    JarvisVariant,
    builtin_policy_path,
)

from intentframe_gateway.config import GatewayConfig
from intentframe_proxy.proxy import UDSProxy
from policy_registry.seeds import load_policy_seed, resolve_seed_path

logger = logging.getLogger(__name__)

__all__ = [
    "Bootstrapper",
    "INTENT_LIMITS",
    "ROOT_WORKSPACE_MOUNTS",
    "SAFE_ACTIONS",
    "UNSAFE_ACTIONS",
    "WORKSPACE_MOUNTS",
    "current_jarvis_identity",
]


# ── Workspace seed data ──────────────────────────────────────────────────────
#
# Workspace mounts live in the resource registry, not the policy
# registry, so they intentionally stay inline here rather than moving
# into a YAML.  Mirrors ``jarvis_pa/executor.yaml::pack_options.files.mounts``
# and ``jarvis_pa/executor_root.yaml::pack_options.files.mounts``.
WORKSPACE_MOUNTS: list[dict[str, Any]] = [
    {"virtual_path": "/home/", "real_path": "~/", "writable": True},
]

ROOT_WORKSPACE_MOUNTS: list[dict[str, Any]] = [
    {"virtual_path": "/", "real_path": "/", "writable": True},
]


# ── Variant + identity resolution ────────────────────────────────────────────


def _resolve_variant(raw: str | None = None) -> JarvisVariant:
    """Resolve the active Jarvis variant.

    Args:
        raw: Explicit value (e.g. from a CLI flag).  Falls back to the
            ``JARVIS_VARIANT`` environment variable, then ``"user"``.

    Unknown values fall back to ``"user"`` with a logged warning so a
    typo never silently relaxes policy.
    """
    candidate = raw if raw is not None else os.environ.get("JARVIS_VARIANT")
    normalised = (candidate or "user").strip().lower()
    if normalised not in JARVIS_AGENT_IDS:
        logger.warning(
            "Unknown JARVIS_VARIANT=%r — falling back to 'user'", normalised
        )
        return "user"
    return normalised  # type: ignore[return-value]


def _resolve_user_id() -> str:
    """Operator/owner ``user_id`` from gateway config + env.

    Reads ``identity.user_id`` from ``~/.intentframe/gateway.yaml`` via
    :mod:`intentframe_gateway.config_loader` first; that loader exposes
    the value as the ``JARVIS_USER_ID`` env-key in its returned dict
    (the historical key — kept stable so the YAML config schema doesn't
    break).  Falls back to ``"jarvis_default"``.
    """
    from intentframe_gateway.config_loader import build_config_env
    return build_config_env().get("JARVIS_USER_ID", "jarvis_default")


def _workspace_id_for(variant: JarvisVariant, user_id: str) -> str:
    """Workspace registry key for a Jarvis variant.

    Returns the bare ``user_id``; both variants share the same slot.
    The resource registry is in-memory and re-built on every supervisor
    start, so only one variant is ever live in it at a time — meaning
    no per-variant suffix is needed for isolation.  ``variant`` is kept
    on the signature so we can still distinguish in audit logs / metadata
    without changing the key.
    """
    del variant  # workspace_id no longer encodes the variant
    return user_id


def current_jarvis_identity(
    variant: JarvisVariant | None = None,
) -> tuple[str, str]:
    """Return ``(user_id, agent_id)`` for the active Jarvis variant.

    Child processes (Jarvis, Telegram bridge) MUST receive these as
    ``INTENTFRAME_USER_ID`` / ``INTENTFRAME_AGENT_ID`` so their
    Actor SDK looks up the same ``(user_id, agent_id)`` slot
    :class:`Bootstrapper` seeded.  Without that alignment the gateway
    logs "No policy for user=… agent=…" and applies unsafe defaults
    (no allowed actions).
    """
    resolved_variant = _resolve_variant(variant)
    return _resolve_user_id(), JARVIS_AGENT_IDS[resolved_variant]


# ── Policy-seed builders ─────────────────────────────────────────────────────


def _profile_workspace_mounts(variant: JarvisVariant) -> list[dict[str, Any]]:
    return ROOT_WORKSPACE_MOUNTS if variant == "root" else WORKSPACE_MOUNTS


def _build_jarvis_policy(variant: JarvisVariant = "user") -> dict[str, Any]:
    """Build the seed-policy dict the registry POSTs for ``variant``.

    Returns the JSON-shaped dict (no ``created_at`` field) so it can be
    sent over HTTP unmodified.  Resolution order for the YAML:

    1. ``~/.intentframe/policies/<agent_id>.yaml`` (user override)
    2. ``jarvis/policies/<filename>.yaml`` (packaged builtin)

    Runtime overlays applied here:

    * ``user_id`` — the gateway-resolved owner id.
    * ``agent_id`` — explicit override of the YAML's value (defensive;
      they always agree because the YAML's ``agent_id`` and the file
      name come from the same source of truth).
    * ``metadata.note`` — stamped to "Auto-seeded by gateway bootstrap"
      so audit consumers can tell a runtime-seeded policy from a
      hand-edited one.
    """
    user_id = _resolve_user_id()
    agent_id = JARVIS_AGENT_IDS[variant]
    yaml_path = resolve_seed_path(agent_id, builtin_policy_path(variant))

    policy = load_policy_seed(
        yaml_path,
        user_id=user_id,
        agent_id=agent_id,
        metadata={"note": "Auto-seeded by gateway bootstrap"},
    )
    return policy.model_dump(mode="json", exclude={"created_at"})


def _build_default_policy() -> dict[str, Any]:
    """Backwards-compatible alias for the user-variant Jarvis policy.

    Intentionally env-independent: ``tests/test_jarvis_host_scope_mirror.py``
    calls this directly to pin the ``jarvis_pa/executor.yaml`` ↔ policy
    mirror, so its return value must not change under
    ``JARVIS_VARIANT=root``.
    """
    return _build_jarvis_policy("user")


# ── Derived module-level lists ───────────────────────────────────────────────
#
# Historically these were hand-maintained tuples in this file.  After
# the YAML-seed refactor they are derived once at import time from the
# user-variant Jarvis policy, which is the canonical surface for the
# runtime defaults (mirrored exactly in the root variant).  This keeps
# the legacy attribute names (referenced by docs and external tooling)
# working without re-introducing the drift hazard the refactor
# eliminates.
def _split_safe_unsafe(seed_dict: dict[str, Any]) -> tuple[list[str], list[str]]:
    safe: list[str] = []
    unsafe: list[str] = []
    for action, perm in seed_dict.get("allowed_actions", {}).items():
        (safe if perm.get("safe") else unsafe).append(action)
    return safe, unsafe


_USER_SEED = load_policy_seed(
    builtin_policy_path("user"),
    user_id="jarvis_default",
).model_dump(mode="json", exclude={"created_at"})
SAFE_ACTIONS, UNSAFE_ACTIONS = _split_safe_unsafe(_USER_SEED)
INTENT_LIMITS: list[dict[str, Any]] = list(_USER_SEED.get("intent_limits", []))
del _USER_SEED


# ── Bootstrapper ─────────────────────────────────────────────────────────────


class Bootstrapper:
    """Idempotent bootstrap: ensure Jarvis policy and workspace exist."""

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

        variant = _resolve_variant()
        user_id = _resolve_user_id()
        agent_id = JARVIS_AGENT_IDS[variant]

        resp = await client.get(f"/policies/{user_id}/{agent_id}")
        if resp.status_code == 200:
            logger.info(
                "Policy already exists for user=%r agent=%r (variant=%s) — skipping seed",
                user_id, agent_id, variant,
            )
            return

        policy = _build_jarvis_policy(variant)
        resp = await client.post("/policies", json=policy)
        if resp.status_code in (200, 201):
            allowed = policy.get("allowed_actions", {})
            safe_n = sum(1 for p in allowed.values() if p.get("safe"))
            unsafe_n = len(allowed) - safe_n
            logger.info(
                "Policy seeded for user=%r agent=%r (variant=%s): "
                "%d actions (%d safe, %d unsafe), %d intent limits",
                user_id, agent_id, variant,
                len(allowed), safe_n, unsafe_n,
                len(policy.get("intent_limits", [])),
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
            from intentframe_proxy.proxy import UDSProxy as _P
            rr_proxy = _P(socket_path=str(sock_path), base_url="http://resource-registry")

        client = await rr_proxy._get_client()

        variant = _resolve_variant()
        user_id = _resolve_user_id()
        agent_id = JARVIS_AGENT_IDS[variant]
        workspace_id = _workspace_id_for(variant, user_id)
        mounts = _profile_workspace_mounts(variant)
        payload = {
            "workspace_id": workspace_id,
            "mounts": mounts,
            "metadata": {"agent": agent_id, "variant": variant},
        }
        resp = await client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            logger.info(
                "Workspace %s already exists (variant=%s) — skipping seed",
                workspace_id, variant,
            )
        elif resp.status_code in (200, 201):
            logger.info(
                "Workspace seeded (variant=%s, workspace_id=%s): %d mount(s)",
                variant, workspace_id, len(mounts),
            )
        else:
            logger.error("Failed to seed workspace: %s %s", resp.status_code, resp.text)
