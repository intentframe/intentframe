"""Root-demo test loader — thin wrapper over :func:`policy_registry.seeds.load_policy_seed`."""

from __future__ import annotations

from pathlib import Path

from policy_registry.models import UserPolicy
from policy_registry.seeds import load_policy_seed

DEFAULT_ROOT_POLICY_PATH = (
    Path(__file__).resolve().parent / "test_policy_root_admin_assistant.yaml"
)

# Root-demo YAMLs register against the stub pipeline agent's id so the
# registry's (user_id, agent_id) slot matches what the demo's
# StubPipelineRootAgent (subclass of StubPipelineAgent) actually sends
# during handshake.  Mismatch here = "no policy found" + everything
# denied, even though seeding "succeeded".
#
# Inlined (rather than imported) because this module loads both as
# top-level (demo runners' sys.path) and as a package member (pytest
# discovery), and a cross-package import only resolves in the first
# context.  Keep in lockstep with
# ``demo/tests/stub_pipeline_agent.py::STUB_PIPELINE_AGENT_ID``;
# ``tests/test_demo_loader_agent_id_in_sync.py`` pins them together.
ROOT_DEMO_AGENT_ID = "stub_pipeline_agent"


def load_root_demo_policy(
    user_id: str,
    policy_path: Path | None = None,
    *,
    agent_id: str = ROOT_DEMO_AGENT_ID,
) -> UserPolicy:
    return load_policy_seed(
        policy_path or DEFAULT_ROOT_POLICY_PATH,
        user_id=user_id,
        agent_id=agent_id,
        metadata={"profile": "root-demo-test"},
    )
