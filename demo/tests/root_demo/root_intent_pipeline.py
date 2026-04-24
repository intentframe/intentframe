"""
Root-demo setup helpers.

Tests import these to seed the per-test policy and workspace before driving
the Actor session themselves.  The session loop (open → submit each intent →
close) lives in the test file, not here — keeping this module a thin facade
over the registry clients.

Supervisor/gateway preconditions are the caller's responsibility.  Either:
  * ``intentframe-gateway-cli --profile root`` (see intentframe_cli/README.md)
  * or a direct ``python -m supervisor.main start`` with
    ``INTENTFRAME_PROFILE=root``, ``EXECUTOR_CONFIG=jarvis_pa/executor_root.yaml``,
    and ``INTENTFRAME_ESCALATION_ARMED=1`` when root-demo is installed
    (see ``docs/executor-root-mode.md``, section 2a).

This module does not start or reconfigure the supervisor itself.
"""

from __future__ import annotations

from policy_registry.client import PolicyRegistryClient
from resource_registry.client import ResourceRegistryClient
from resource_registry.models import ResourceMount

from root_policy_loader import load_root_demo_policy

DEFAULT_INTENTFRAME_SOCKET = "~/.intentframe/run/intentframe.sock"

ROOT_USER_ID = "root_demo_tester"


def ensure_root_user_policy(policy_client: PolicyRegistryClient) -> None:
    policy_client.set_user_policy(load_root_demo_policy(ROOT_USER_ID))


def register_root_workspace(resource_client: ResourceRegistryClient) -> None:
    """Mount the real root as the virtual root, mirroring executor_root.yaml."""
    try:
        resource_client.delete_workspace(ROOT_USER_ID)
    except Exception:
        pass
    resource_client.create_workspace(
        workspace_id=ROOT_USER_ID,
        mounts=[
            ResourceMount(virtual_path="/", real_path="/", writable=True),
        ],
        base_path="/",
    )
