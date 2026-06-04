"""
Shared setup helpers for invoice-based attack tests.

Tests import these helpers and drive the Actor session themselves — seed
policy + workspace once, open the stub agent once, then loop through attacks
resetting only per-attack state (tracker, sandbox, audit) between runs.  The
single-session pattern means onboarding fires exactly once per test run
regardless of how many attacks are exercised.

Callers:
  - ``test_attacks.py`` and ``test_advanced_attacks.py`` call
    ``populate_attack_sandbox()`` before each attack (legacy invoice/VFS setup).
    Most fixtures submit ``APPEND_ROW`` directly and block before executor I/O;
    only attack 4 prelude reads on ``/invoices/`` care about the sandbox.
  - ``test_redteam_attacks.py`` does **not** use this module's sandbox helpers.

Prerequisites:
  - Repo root as current working directory when starting supervisor.
  - Supervisor with attack executor config + the kit profile (this module calls
    ResourceRegistryClient.create_workspace, so resource-registry must be up)::

      EXECUTOR_CONFIG=demo/config/executor_attacks.yaml \
      python -m supervisor.main start \
        --config "${KIT}/supervisor_profile.yaml"

  Over HTTP against ``deploy/dev/`` container: defense validation works without
  Mac/container filesystem sync; see ``deploy/dev/README.md`` §2c.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from policy_registry.client import PolicyRegistryClient
from intentframe_native_kit.resource_registry.client import ResourceRegistryClient
from intentframe_native_kit.resource_registry.models import ResourceMount

from intentframe_client import IntentFrameClient

from policy_loader import load_test_policy

DEFAULT_INTENTFRAME_SOCKET = "~/.intentframe/run/intentframe.sock"

ATTACK_USER_ID = "attack_tester"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = _REPO_ROOT / "demo"
DEMO_DATA = DEMO_ROOT / "demo_data"
SANDBOX_DIR = DEMO_DATA / "attack_invoices_sandbox"


def reset_expense_tracker() -> None:
    original = DEMO_DATA / "expense_tracker_original_locked.md"
    target = DEMO_DATA / "expense_tracker.md"
    if original.exists():
        shutil.copy(original, target)


def populate_attack_sandbox(attack_folder: str) -> None:
    """Copy only this scenario's invoice markdown into the executor sandbox."""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    for f in SANDBOX_DIR.glob("*.md"):
        f.unlink(missing_ok=True)
    src_dir = DEMO_DATA / "attacks" / attack_folder
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Attack data not found: {src_dir}")
    for md in src_dir.glob("*.md"):
        shutil.copy(md, SANDBOX_DIR / md.name)


def ensure_attack_user_policy(policy_client: PolicyRegistryClient) -> None:
    policy = load_test_policy(ATTACK_USER_ID, metadata={"profile": "attack-tester"})
    policy_client.set_user_policy(policy)


def register_attack_workspace(resource_client: ResourceRegistryClient) -> None:
    """Register workspace keyed by user id; mirrors executor_attacks.yaml mounts."""
    try:
        resource_client.delete_workspace(ATTACK_USER_ID)
    except Exception:
        pass
    resource_client.create_workspace(
        workspace_id=ATTACK_USER_ID,
        mounts=[
            ResourceMount(
                virtual_path="/invoices/",
                real_path="demo_data/attack_invoices_sandbox",
                file_filter="*.md",
            ),
            ResourceMount(
                virtual_path="/expense_tracker.md",
                real_path="demo_data/expense_tracker.md",
                writable=True,
            ),
        ],
        base_path=str(DEMO_ROOT),
    )


def snapshot_audit(server_client: IntentFrameClient) -> dict[str, Any]:
    """Pull the current audit log and bucket it by decision type.

    ``blocked_append_rows`` is invoice-specific — used by test summaries to
    surface "Blocked: <vendor> (<amount>)" rows.
    """
    audit_log = server_client.get_audit_log()
    blocked_count = sum(1 for e in audit_log if e.get("decision") == "BLOCK")
    allowed_count = sum(1 for e in audit_log if e.get("decision") == "ALLOW")
    blocked_append_rows = [
        e
        for e in audit_log
        if e.get("decision") == "BLOCK" and e.get("action") == "APPEND_ROW"
    ]
    return {
        "audit_log": audit_log,
        "blocked_count": blocked_count,
        "allowed_count": allowed_count,
        "blocked_append_rows": blocked_append_rows,
    }
