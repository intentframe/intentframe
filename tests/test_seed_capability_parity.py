"""Pin the YAML ↔ Python-constants invariant for built-in Jarvis seeds.

The packaged Jarvis YAMLs under :mod:`jarvis.policies` carry the
``RUN_COMMAND.constraints.deny_capabilities`` list literally — they
are the source of truth for the gateway's runtime seed.  The same
set is exposed as a Python ``frozenset`` constant
(:data:`intentframe_native_kit.intentframe_native_bundles.actions.terminal.capabilities.DEFAULT_TERMINAL_DENY_CAPABILITIES`)
for the deterministic-accuracy and classifier-contract tests that
compare against named values rather than parsing YAML.

Two copies; one source of truth.  This module pins them in lockstep so
adding / removing a capability in one place but not the other fails
loudly in CI.

What the tests check
--------------------
* Both Jarvis YAMLs produce a ``RUN_COMMAND`` ``deny_capabilities`` list
  that equals ``sorted(DEFAULT_TERMINAL_DENY_CAPABILITIES)``.
* The two variants deny the same capability set (the language /
  sensitive surface clamp is variant-independent on purpose).
"""

from __future__ import annotations

import pytest

from intentframe_native_kit.intentframe_native_bundles.actions.terminal.capabilities import (
    DEFAULT_TERMINAL_DENY_CAPABILITIES,
    PYTHON_SHELL_ONLY_DENY_CAPABILITIES,
    SENSITIVE_SURFACE_DENY_CAPABILITIES,
)
from jarvis.policies import builtin_policy_path
from policy_registry.seeds import load_policy_seed


@pytest.mark.parametrize("variant", ["user", "root"])
def test_yaml_deny_capabilities_equal_constants(variant: str) -> None:
    """Each Jarvis YAML's RUN_COMMAND deny list mirrors the constant.

    ``TerminalConstraints.deny_capabilities`` is typed as ``frozenset[str]``
    so the comparison is set-equality rather than list-equality.
    """
    policy = load_policy_seed(builtin_policy_path(variant), user_id="parity")  # type: ignore[arg-type]
    perm = policy.allowed_actions["RUN_COMMAND"]
    assert perm.constraints is not None, "RUN_COMMAND must carry TerminalConstraints"
    yaml_caps = set(perm.constraints.get("deny_capabilities") or [])
    expected = set(DEFAULT_TERMINAL_DENY_CAPABILITIES)
    assert yaml_caps == expected, (
        f"{variant} variant's RUN_COMMAND.deny_capabilities drifted from "
        f"DEFAULT_TERMINAL_DENY_CAPABILITIES.\n"
        f"  in YAML, missing from constants: {sorted(yaml_caps - expected)!r}\n"
        f"  in constants, missing from YAML: {sorted(expected - yaml_caps)!r}"
    )


def test_user_and_root_variants_share_deny_set() -> None:
    """The clamp is variant-independent on purpose; pin that explicitly."""
    user = load_policy_seed(builtin_policy_path("user"), user_id="parity").allowed_actions[
        "RUN_COMMAND"
    ].constraints
    root = load_policy_seed(builtin_policy_path("root"), user_id="parity").allowed_actions[
        "RUN_COMMAND"
    ].constraints
    assert user is not None and root is not None
    assert set(user.get("deny_capabilities") or []) == set(root.get("deny_capabilities") or []), (
        "user and root Jarvis variant RUN_COMMAND deny_capabilities drifted apart; "
        "the language- and sensitive-surface clamps are variant-independent."
    )


def test_constant_is_union_of_two_clamps() -> None:
    """``DEFAULT_TERMINAL_DENY_CAPABILITIES`` stays the union of the two clamps."""
    assert DEFAULT_TERMINAL_DENY_CAPABILITIES == (
        PYTHON_SHELL_ONLY_DENY_CAPABILITIES | SENSITIVE_SURFACE_DENY_CAPABILITIES
    )
