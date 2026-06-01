"""Loader boot path and startup validation invariants."""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from intentframe_bundle_sdk.action import ActionBundle
from intentframe_bundle_sdk.loader import ensure_loaded, validate_policy_against_registry
from intentframe_bundle_sdk.registry import (
    action_bundle_for,
    register_action_bundle,
)
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
from policy_registry.models import ActionPermission, UserPolicy
from tests._bundle_loader import DEFAULT_TEST_PACKAGES, ensure_test_bundles_loaded


def test_ensure_loaded_is_idempotent() -> None:
    first = ensure_loaded(DEFAULT_TEST_PACKAGES)
    second = ensure_loaded(DEFAULT_TEST_PACKAGES)
    assert first
    assert second
    assert {b.bundle_id for b in first} == {b.bundle_id for b in second}


def test_ensure_loaded_rejects_conflicting_package_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import intentframe_bundle_sdk.loader as loader_mod

    monkeypatch.setattr(loader_mod, "_LOADED_PACKAGES", frozenset({"intentframe_native_kit.intentframe_native_bundles"}))
    with pytest.raises(RuntimeError, match="already loaded"):
        ensure_loaded(["some.other.package"])


def test_ensure_loaded_requires_register_bundles(monkeypatch: pytest.MonkeyPatch) -> None:
    import intentframe_bundle_sdk.loader as loader_mod

    monkeypatch.setattr(loader_mod, "_LOADED_PACKAGES", None)
    fake = types.ModuleType("fake_bundle_pkg_no_register")
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    with pytest.raises(ImportError, match="register_bundles"):
        ensure_loaded([fake.__name__])


def test_ensure_loaded_import_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    import intentframe_bundle_sdk.loader as loader_mod

    monkeypatch.setattr(loader_mod, "_LOADED_PACKAGES", None)

    def _boom(_name: str):
        raise ImportError("missing plugin")

    monkeypatch.setattr(importlib, "import_module", _boom)
    with pytest.raises(ImportError, match="failed to import"):
        ensure_loaded(["nonexistent.package.xyz"])


def test_validate_policy_rejects_bad_terminal_constraint_shape() -> None:
    ensure_test_bundles_loaded()
    policy = UserPolicy(
        user_id="u",
        agent_id="a",
        allowed_actions={
            "RUN_COMMAND": ActionPermission(
                safe=False,
                constraints={"blocked_patterns": "must-be-list"},
            ),
        },
    )
    with pytest.raises(Exception):
        validate_policy_against_registry(policy)


def test_validate_policy_requires_validate_constraints_override() -> None:
    ensure_test_bundles_loaded()

    class NoValidateBundle(ActionBundle):
        bundle_id = "no_validate"
        action_ids = frozenset({"TEST_NO_VALIDATE"})

    register_action_bundle(NoValidateBundle())
    policy = UserPolicy(
        user_id="u",
        agent_id="a",
        allowed_actions={
            "TEST_NO_VALIDATE": ActionPermission(
                safe=True,
                constraints={"any": "shape"},
            ),
        },
    )
    with pytest.raises(NotImplementedError, match="validate_constraints"):
        validate_policy_against_registry(policy)


def test_validate_policy_requires_registered_bundle_for_allowed_action() -> None:
    ensure_test_bundles_loaded()
    policy = UserPolicy(
        user_id="u",
        agent_id="a",
        allowed_actions={
            "GHOST_ACTION": ActionPermission(safe=True),
        },
    )
    with pytest.raises(ValueError, match="no registered ActionBundle"):
        validate_policy_against_registry(policy)


def test_terminal_bundle_resolves_for_run_command() -> None:
    ensure_test_bundles_loaded()
    bundle = action_bundle_for("RUN_COMMAND")
    assert isinstance(bundle, TerminalActionBundle)
