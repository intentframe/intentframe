"""Load the root-demo test policy YAML into a UserPolicy."""

from __future__ import annotations

from pathlib import Path

from policy_loader import load_test_policy
from policy_registry.models import UserPolicy

DEFAULT_ROOT_POLICY_PATH = Path(__file__).resolve().parent / "test_policy_root_admin_assistant.yaml"


def load_root_demo_policy(
    user_id: str,
    policy_path: Path | None = None,
) -> UserPolicy:
    return load_test_policy(
        user_id,
        yaml_path=policy_path or DEFAULT_ROOT_POLICY_PATH,
        metadata={"profile": "root-demo-test"},
    )
