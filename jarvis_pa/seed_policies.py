"""Dev CLI — seed the Policy Registry and Resource Registry for Jarvis.

Run after the supervisor is up:

    python jarvis_pa/seed_policies.py            # user variant
    JARVIS_VARIANT=root python jarvis_pa/seed_policies.py   # root variant

The actual policy data lives in ``jarvis/policies/jarvis.yaml`` (and
``jarvis_root.yaml``) and is loaded via
:func:`policy_registry.seeds.load_policy_seed` — the same loader the
gateway's :class:`intentframe_gateway.bootstrap.Bootstrapper` uses on
every startup.  This script is a hand-runnable convenience wrapper
around that loader plus the HTTP plumbing to POST the seeds into the
running registries over their UNIX domain sockets.

Variants
--------
Selected via ``JARVIS_VARIANT``:

* ``user`` (default) — home-scoped host-file access (``~/*``), virtual
  workspace rooted at ``/home/``.  Mirrors ``jarvis_pa/executor.yaml``.
  Registers under ``agent_id="jarvis"``.
* ``root`` — full-filesystem host-file access (``/*``), virtual workspace
  rooted at ``/``.  Mirrors ``jarvis_pa/executor_root.yaml``.  Registers
  under ``agent_id="jarvis_root"``.

Customisation
-------------
Drop a YAML at ``~/.intentframe/policies/<agent_id>.yaml`` (e.g.
``~/.intentframe/policies/jarvis.yaml``) to override the packaged
builtin.  Re-run this script (or restart the gateway) to seed the new
policy.

Idempotent: GETs the policy first and skips POST if it already exists;
the resource-registry workspace POST is idempotent on the registry's
409 response.

For development/testing only — the gateway already does this on every
startup.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx

from jarvis.policies import (
    JARVIS_AGENT_IDS,
    JarvisVariant,
    builtin_policy_path,
)
from intentframe_bundle_sdk.loader import validate_policy_with_bundles
from intentframe_server.config import CoreConfigurationError, load_core_config
from policy_registry.seeds import (
    load_policy_seed,
    resolve_seed_path,
    resolve_user_id,
)

logger = logging.getLogger(__name__)

POLICY_REGISTRY_SOCKET = "~/.intentframe/run/policy-registry.sock"
RESOURCE_REGISTRY_SOCKET = "~/.intentframe/run/resource-registry.sock"


# Workspace mounts live in the resource registry rather than the policy
# registry, so they stay inline here (and in
# ``intentframe_gateway/bootstrap.py``) instead of being part of the
# YAML seed.  Mirrors ``jarvis_pa/executor.yaml::pack_options.files.mounts``
# and ``jarvis_pa/executor_root.yaml::pack_options.files.mounts``.
WORKSPACE_MOUNTS = [
    {"virtual_path": "/home/", "real_path": "~/", "writable": True},
]

ROOT_WORKSPACE_MOUNTS = [
    {"virtual_path": "/", "real_path": "/", "writable": True},
]


def _resolve_variant() -> JarvisVariant:
    raw = (os.environ.get("JARVIS_VARIANT") or "user").strip().lower()
    if raw not in JARVIS_AGENT_IDS:
        print(f"Warning: unknown JARVIS_VARIANT={raw!r} — falling back to 'user'")
        return "user"
    return raw  # type: ignore[return-value]


def _variant_workspace_mounts(variant: JarvisVariant) -> list[dict]:
    return ROOT_WORKSPACE_MOUNTS if variant == "root" else WORKSPACE_MOUNTS


def _workspace_id_for(variant: JarvisVariant, user_id: str) -> str:
    """Workspace registry key for the Jarvis variant.

    Mirrors :func:`intentframe_gateway.bootstrap._workspace_id_for` —
    keep these in lockstep.  Returns the bare ``user_id`` so the
    pipeline's ``_resolve_workspace(user_id)`` lookup hits the same
    slot the bootstrap seeded.
    """
    del variant
    return user_id


def _build_policy_payload(variant: JarvisVariant, user_id: str) -> dict:
    """Build the JSON-shaped policy dict the registry POST accepts."""
    agent_id = JARVIS_AGENT_IDS[variant]
    yaml_path = resolve_seed_path(agent_id, builtin_policy_path(variant))
    policy = load_policy_seed(
        yaml_path,
        user_id=user_id,
        agent_id=agent_id,
        metadata={"note": "Auto-seeded by seed_policies.py"},
    )
    packages = _configured_bundle_packages()
    if packages is not None:
        validate_policy_with_bundles(policy, packages)
    return policy.model_dump(mode="json", exclude={"created_at"})


def _configured_bundle_packages() -> list[str] | None:
    """Use the active core profile for seed validation when one is declared."""
    if not os.environ.get("INTENTFRAME_CORE_CONFIG"):
        return None
    try:
        return load_core_config().bundles
    except CoreConfigurationError as exc:
        raise SystemExit(f"Invalid core bundle configuration: {exc}") from exc


def _seed_workspace(socket_path: str, variant: JarvisVariant, user_id: str) -> None:
    """Register Jarvis's workspace in the Resource Registry."""
    workspace_id = _workspace_id_for(variant, user_id)
    mounts = _variant_workspace_mounts(variant)
    transport = httpx.HTTPTransport(uds=socket_path)
    with httpx.Client(transport=transport, base_url="http://resource-registry") as client:
        payload = {
            "workspace_id": workspace_id,
            "mounts": mounts,
            "metadata": {"agent": JARVIS_AGENT_IDS[variant], "variant": variant},
        }
        resp = client.post("/workspaces", json=payload)
        if resp.status_code == 409:
            print(f"Workspace {workspace_id} already exists (variant={variant}) — skipping")
            return
        resp.raise_for_status()
        print(f"Workspace seeded: {resp.json().get('workspace_id')} (variant={variant})")
        print(f"  Mounts: {len(mounts)}")
        for m in mounts:
            rw = "read/write" if m.get("writable") else "read"
            print(f"    - {m['virtual_path']} → {m['real_path']} ({rw})")


def main() -> None:
    policy_sock = Path(POLICY_REGISTRY_SOCKET).expanduser()
    resource_sock = Path(RESOURCE_REGISTRY_SOCKET).expanduser()

    if not policy_sock.exists():
        print(f"Error: Policy registry socket not found at {policy_sock}")
        print(
            "Start the supervisor first with the kit profile (resource-registry "
            "required). From repo root, see demo/README.md for the KIT=… "
            "supervisor start command."
        )
        sys.exit(1)

    variant = _resolve_variant()
    user_id = resolve_user_id()
    agent_id = JARVIS_AGENT_IDS[variant]
    print(f"Active variant: {variant}  (user_id={user_id!r}, agent_id={agent_id!r})")

    payload = _build_policy_payload(variant, user_id)

    transport = httpx.HTTPTransport(uds=str(policy_sock))
    with httpx.Client(transport=transport, base_url="http://policy-registry") as client:
        existing = client.get(f"/policies/{user_id}/{agent_id}")
        if existing.status_code == 200:
            print(
                f"Policy already exists for user={user_id!r} agent={agent_id!r} "
                f"(variant={variant}) — skipping"
            )
        else:
            resp = client.post("/policies", json=payload)
            resp.raise_for_status()
            print(f"Policy seeded: {resp.json()}")

            allowed = payload.get("allowed_actions", {})
            safe_n = sum(1 for p in allowed.values() if p.get("safe"))
            unsafe_n = len(allowed) - safe_n
            limits = payload.get("intent_limits", [])
            print(f"  Allowed actions: {len(allowed)} ({safe_n} safe, {unsafe_n} AI-validated)")
            print(f"  Intent limits:   {len(limits)}")
            for lim in limits:
                print(f"    - [{lim['domain']}] {lim['description']} → {lim['effect']}")

    if resource_sock.exists():
        _seed_workspace(str(resource_sock), variant, user_id)
    else:
        print(f"Warning: Resource registry socket not found at {resource_sock} — workspace not seeded")


if __name__ == "__main__":
    main()
