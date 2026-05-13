"""Drift guard: demo policy loaders register under the stub agent's id.

The demo suites all drive IntentFrame through ``StubPipelineAgent``
(and its ``StubPipelineRootAgent`` subclass), which hardcodes the
``agent_id`` it sends on every handshake/submit.  The policy registry
keys on the ``(user_id, agent_id)`` pair, so if the loaders seed under
a different ``agent_id`` than the stub presents, every lookup misses
and every action is denied with ``"no policy for user/agent"`` even
though seeding "succeeded".

That regression already shipped once during the YAML-seed refactor
(loaders defaulted to ``f"{user_id}-agent"`` / ``"jarvis_root_demo"``,
neither of which matches the stub).  This test pins all three constants
to the same string so a one-sided rename fails CI here instead of
manifesting as silently-blocked demos.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_DEMO_TESTS = _REPO / "demo" / "tests"
_ROOT_DEMO = _DEMO_TESTS / "root_demo"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"could not build spec for {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def constants() -> dict[str, str]:
    """Load the three modules out-of-package and read their constants.

    Loaded by file path so this test doesn't depend on the demo
    runners' ``sys.path`` munging; we just need the literals.
    """
    stub = _load_module(
        "stub_pipeline_agent_under_test",
        _DEMO_TESTS / "stub_pipeline_agent.py",
    )
    loader = _load_module(
        "policy_loader_under_test",
        _DEMO_TESTS / "policy_loader.py",
    )
    root_loader = _load_module(
        "root_policy_loader_under_test",
        _ROOT_DEMO / "root_policy_loader.py",
    )
    return {
        "stub":        stub.STUB_PIPELINE_AGENT_ID,
        "loader":      loader._STUB_PIPELINE_AGENT_ID,
        "root_loader": root_loader.ROOT_DEMO_AGENT_ID,
    }


def test_all_demo_loaders_match_stub_agent_id(constants: dict[str, str]) -> None:
    assert constants["loader"] == constants["stub"], (
        "demo/tests/policy_loader.py defaults to a different agent_id "
        f"({constants['loader']!r}) than the stub presents "
        f"({constants['stub']!r}) — registry lookups will miss and every "
        "attack/red-team submit will be blocked with 'no policy for user/agent'."
    )
    assert constants["root_loader"] == constants["stub"], (
        "demo/tests/root_demo/root_policy_loader.py defaults to a different "
        f"agent_id ({constants['root_loader']!r}) than the stub presents "
        f"({constants['stub']!r}) — root-demo walkthrough will fail preflight."
    )
