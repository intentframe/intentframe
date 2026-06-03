"""Test loader — thin wrapper over :func:`policy_registry.seeds.load_policy_seed`.

Both the attack and red-team test suites call :func:`load_test_policy`
with their suite-specific ``user_id``.  The policy definition lives in
``demo/config/test_policy.yaml`` so changes propagate to every suite,
and parsing goes through the same loader the gateway and dev seed CLI
use — :func:`policy_registry.seeds.load_policy_seed` — so the test
fixtures and the production seeders share one validation path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from intentframe_native_kit.intentframe_native_bundles.actions.api.constraints import ApiConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.browser.constraints import BrowserConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.calendar.constraints import CalendarConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.email.constraints import EmailConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.files.constraints import FileConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.host_files.constraints import HostFileConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.message.constraints import MessageConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints
from intentframe_bundle_sdk.loader import validate_policy_with_bundles
from policy_registry.models import ActionPermission, UserPolicy
from policy_registry.seeds import load_policy_seed

_DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "test_policy.yaml"
)

# Inlined (rather than imported) because this module is loaded both as a
# top-level script (demo runners that ``sys.path.insert(0, "demo/tests")``)
# and as the package module ``demo.tests.policy_loader`` (pytest), and a
# cross-import to ``stub_pipeline_agent`` only resolves in the first
# context.  Keep this string in lockstep with
# ``demo/tests/stub_pipeline_agent.py::STUB_PIPELINE_AGENT_ID``;
# ``tests/test_demo_loader_agent_id_in_sync.py`` pins them together.
_STUB_PIPELINE_AGENT_ID = "stub_pipeline_agent"
_BUNDLE_PACKAGES = ["intentframe_native_kit.intentframe_native_bundles"]


def load_test_policy(
    user_id: str,
    *,
    agent_id: str = _STUB_PIPELINE_AGENT_ID,
    yaml_path: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> UserPolicy:
    """Build a :class:`UserPolicy` from the shared test YAML.

    Args:
        user_id:   Suite-specific user identifier (e.g. ``"attack_tester"``).
        agent_id:  Agent identifier this policy is for.  Defaults to the
            stub pipeline agent's id so the registry's
            ``(user_id, agent_id)`` slot matches what
            :class:`StubPipelineAgent` sends during handshake — without
            this default the lookup misses and every action is denied
            with "no policy for user/agent".
        yaml_path: Override the default YAML location.
        metadata:  Optional metadata dict merged into the policy.
    """
    policy = load_policy_seed(
        yaml_path or _DEFAULT_POLICY_PATH,
        user_id=user_id,
        agent_id=agent_id,
        metadata=metadata,
    )
    validate_policy_with_bundles(policy, _BUNDLE_PACKAGES)
    return policy


def _parse_constraints(raw: dict[str, Any] | None) -> Any:
    """Return raw constraints unchanged (opaque dict storage).

    Kept as a back-compat helper for callers that previously resolved
    a concrete Pydantic constraint type.  Policy registry now stores
    opaque dicts; family bundles validate shape via
    ``validate_policy_against_registry``.
    """
    if raw is None:
        return None
    return ActionPermission.model_validate({"safe": False, "constraints": raw}).constraints
