"""Tests for :mod:`policy_registry.seeds` — loader, resolver, override discovery.

The loader is the single source of truth for "load a policy YAML",
shared by the gateway bootstrap, the dev seed CLI, the demo loaders,
and external-agent installers.  These tests pin its contract:

* Built-in Jarvis YAMLs round-trip cleanly through
  :class:`UserPolicy.model_validate`.
* User overrides at ``~/.intentframe/policies/<agent_id>.yaml`` win
  over the packaged builtin (the customisation knob for end users).
* The dict shape produced by the loader equals the JSON-shaped dict the
  gateway POSTs to the policy registry — parity invariant with
  :func:`intentframe_gateway.bootstrap._build_jarvis_policy`.
* ``intentframe_schema_version`` is hard-required and hard-validated
  (the friendly-error path for users with stale YAMLs).
* Identity helpers (``resolve_user_id`` / ``resolve_agent_id``) honour
  the env precedence the Actor SDK and the gateway both rely on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from intentframe_gateway import bootstrap
from jarvis.policies import builtin_policy_path
from intentframe_native_kit.intentframe_native_bundles.actions.email.constraints import EmailConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.host_files.constraints import HostFileConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.message.constraints import MessageConstraints
from intentframe_native_kit.intentframe_native_bundles.actions.terminal.constraints import TerminalConstraints
from policy_registry.models import (
    INTENTFRAME_POLICY_SCHEMA_VERSION,
    UserPolicy,
)
from policy_registry.seeds import (
    PolicySchemaVersionError,
    load_policy_seed,
    override_path,
    resolve_agent_id,
    resolve_seed_path,
    resolve_user_id,
)
from policy_registry.seeds import resolver as _resolver


# ── Loader smoke tests ───────────────────────────────────────────────────────


@pytest.mark.parametrize("variant", ["user", "root"])
def test_builtin_jarvis_loads_cleanly(variant: str) -> None:
    policy = load_policy_seed(
        builtin_policy_path(variant),  # type: ignore[arg-type]
        user_id=f"unit_{variant}",
    )
    assert isinstance(policy, UserPolicy)
    assert policy.user_id == f"unit_{variant}"
    assert policy.agent_id in {"jarvis", "jarvis_root"}
    assert policy.intentframe_schema_version == INTENTFRAME_POLICY_SCHEMA_VERSION
    assert policy.allowed_actions, "loaded policy has zero allowed actions"
    assert policy.intent_limits, "loaded policy has zero intent limits"


def test_host_file_actions_dispatch_to_host_file_constraints() -> None:
    """Disjoint-field invariant — pinned by tests/test_policy_host_constraints_roundtrip.py."""
    user = load_policy_seed(builtin_policy_path("user"), user_id="unit_user")
    for action in (
        "READ_HOST_FILE",
        "LIST_HOST_DIRECTORY",
        "WRITE_HOST_FILE",
        "DELETE_HOST_FILE",
    ):
        perm = user.allowed_actions[action]
        assert isinstance(perm.constraints, dict), (
            f"{action} constraint must be stored as opaque dict"
        )
        assert perm.constraints.get("allowed_host_paths") == ["~/*"]


def test_root_variant_broadens_host_paths() -> None:
    root = load_policy_seed(builtin_policy_path("root"), user_id="unit_root")
    perm = root.allowed_actions["READ_HOST_FILE"]
    assert isinstance(perm.constraints, dict)
    assert perm.constraints.get("allowed_host_paths") == ["/*"]


def test_email_and_message_constraints_dispatch_correctly() -> None:
    user = load_policy_seed(builtin_policy_path("user"), user_id="unit_user")
    assert "allowed_recipients" in (user.allowed_actions["SEND_EMAIL"].constraints or {})
    assert "allowed_recipients" in (user.allowed_actions["REPLY_EMAIL"].constraints or {})
    assert "allowed_contacts" in (user.allowed_actions["SEND_MESSAGE"].constraints or {})
    assert "blocked_patterns" in (user.allowed_actions["RUN_COMMAND"].constraints or {})


def test_metadata_overlay_wins() -> None:
    base = load_policy_seed(builtin_policy_path("user"), user_id="unit_user")
    overlaid = load_policy_seed(
        builtin_policy_path("user"),
        user_id="unit_user",
        metadata={"note": "override-text", "extra_key": "value"},
    )
    assert base.metadata.get("note") != "override-text"
    assert overlaid.metadata["note"] == "override-text"
    assert overlaid.metadata["extra_key"] == "value"


def test_explicit_user_id_and_agent_id_win() -> None:
    """Keyword overrides replace whatever the YAML declared."""
    policy = load_policy_seed(
        builtin_policy_path("user"),
        user_id="explicit-user",
        agent_id="explicit-agent",
    )
    assert policy.user_id == "explicit-user"
    assert policy.agent_id == "explicit-agent"


def test_demo_test_policy_domain_constraints_validate_at_load() -> None:
    """Attack/red-team YAML carries domain_constraints; loader must not inject legacy ``domain`` keys."""
    yaml_path = Path(__file__).resolve().parents[1] / "demo" / "config" / "test_policy.yaml"
    policy = load_policy_seed(
        yaml_path,
        user_id="attack_tester",
        agent_id="stub_pipeline_agent",
    )
    finance = policy.domain_constraints["finance"]
    deletion = policy.domain_constraints["deletion"]
    assert finance["max_amount"] == 5000.0
    assert finance["allowed_currencies"] == ["USD"]
    assert deletion["require_confirmation"] is True
    assert deletion["block_irreversible"] is True
    assert "domain" not in finance
    assert "domain" not in deletion


def test_domain_constraints_reject_legacy_domain_field(tmp_path: Path) -> None:
    """domain_constraints values must not carry a legacy ``domain`` discriminator."""
    yaml_path = _write_yaml(
        tmp_path / "legacy_domain_field.yaml",
        "intentframe_schema_version: 1\n"
        "agent_id: stub_pipeline_agent\n"
        "allowed_actions:\n"
        "  PAY_INVOICE:\n"
        "    safe: false\n"
        "    constraints:\n"
        "      max_amount: 5000.0\n"
        "domain_constraints:\n"
        "  finance:\n"
        "    domain: finance\n"
        "    max_amount: 5000.0\n",
    )
    with pytest.raises(ValidationError, match="domain"):
        load_policy_seed(yaml_path, user_id="u", agent_id="stub_pipeline_agent")


# ── Schema version validation ────────────────────────────────────────────────


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_schema_version_raises(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "missing_version.yaml",
        "agent_id: x\nallowed_actions:\n  ASK_USER: {safe: true}\n",
    )
    with pytest.raises(PolicySchemaVersionError, match="missing the required field"):
        load_policy_seed(yaml_path, user_id="u")


def test_wrong_schema_version_raises(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "wrong_version.yaml",
        "intentframe_schema_version: 99\n"
        "agent_id: x\n"
        "allowed_actions:\n  ASK_USER: {safe: true}\n",
    )
    with pytest.raises(PolicySchemaVersionError, match="declares `intentframe_schema_version: 99`"):
        load_policy_seed(yaml_path, user_id="u")


def test_non_integer_schema_version_raises(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "stringy_version.yaml",
        "intentframe_schema_version: \"1\"\n"
        "agent_id: x\n"
        "allowed_actions:\n  ASK_USER: {safe: true}\n",
    )
    with pytest.raises(PolicySchemaVersionError, match="expected an integer"):
        load_policy_seed(yaml_path, user_id="u")


# ── Override discovery ───────────────────────────────────────────────────────


def test_user_override_wins_over_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A YAML at ``~/.intentframe/policies/<agent_id>.yaml`` overrides the builtin."""
    fake_override_dir = tmp_path / "policies"
    fake_override_dir.mkdir()
    override_yaml = fake_override_dir / "jarvis.yaml"
    override_yaml.write_text(
        "intentframe_schema_version: 1\n"
        "agent_id: jarvis\n"
        "metadata: {note: override-test}\n"
        "allowed_actions:\n"
        "  ASK_USER:\n"
        "    safe: true\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(_resolver, "OVERRIDE_DIR", fake_override_dir)

    builtin = builtin_policy_path("user")
    resolved = resolve_seed_path("jarvis", builtin)
    assert resolved == override_yaml

    policy = load_policy_seed(resolved, user_id="override")
    assert policy.metadata.get("note") == "override-test"
    assert set(policy.allowed_actions.keys()) == {"ASK_USER"}


def test_falls_back_to_builtin_when_no_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_override_dir = tmp_path / "empty"
    monkeypatch.setattr(_resolver, "OVERRIDE_DIR", fake_override_dir)

    builtin = builtin_policy_path("user")
    resolved = resolve_seed_path("jarvis", builtin)
    assert resolved == builtin


def test_override_path_requires_agent_id() -> None:
    with pytest.raises(ValueError, match="non-empty agent_id"):
        override_path("")


# ── Identity resolver helpers ────────────────────────────────────────────────


def test_resolve_user_id_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTENTFRAME_USER_ID", raising=False)
    monkeypatch.delenv("JARVIS_USER_ID", raising=False)
    assert resolve_user_id() == "jarvis_default"


def test_resolve_user_id_prefers_intentframe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTENTFRAME_USER_ID", "alice")
    monkeypatch.setenv("JARVIS_USER_ID", "bob")
    assert resolve_user_id() == "alice"


def test_resolve_user_id_falls_back_to_jarvis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTENTFRAME_USER_ID", raising=False)
    monkeypatch.setenv("JARVIS_USER_ID", "bob")
    assert resolve_user_id() == "bob"


def test_resolve_agent_id_returns_default_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTENTFRAME_AGENT_ID", raising=False)
    assert resolve_agent_id(default="jarvis") == "jarvis"
    assert resolve_agent_id() is None


def test_resolve_agent_id_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTENTFRAME_AGENT_ID", "invoice_bot")
    assert resolve_agent_id(default="jarvis") == "invoice_bot"


# ── Parity with bootstrap._build_jarvis_policy ───────────────────────────────


@pytest.mark.parametrize("variant", ["user", "root"])
def test_loader_matches_bootstrap_build_jarvis_policy(
    variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bootstrap dict and the loader output describe the same policy.

    Bootstrap stamps ``metadata.note`` to "Auto-seeded by gateway bootstrap";
    the loader returns whatever is in the YAML.  We compare modulo the
    note text — every other field (allowed_actions, intent_limits,
    user_id, agent_id, schema version) must match exactly.
    """
    monkeypatch.delenv("INTENTFRAME_USER_ID", raising=False)
    monkeypatch.delenv("JARVIS_USER_ID", raising=False)
    monkeypatch.delenv("INTENTFRAME_AGENT_ID", raising=False)

    legacy = bootstrap._build_jarvis_policy(variant)  # type: ignore[arg-type]
    loaded = load_policy_seed(
        builtin_policy_path(variant),  # type: ignore[arg-type]
        user_id=legacy["user_id"],
        agent_id=legacy["agent_id"],
    ).model_dump(mode="json", exclude={"created_at"})

    legacy_meta = dict(legacy["metadata"])
    loaded_meta = dict(loaded["metadata"])
    legacy_meta.pop("note", None)
    loaded_meta.pop("note", None)
    assert legacy_meta == loaded_meta

    assert legacy["user_id"] == loaded["user_id"]
    assert legacy["agent_id"] == loaded["agent_id"]
    assert legacy["intentframe_schema_version"] == loaded["intentframe_schema_version"]
    assert legacy["intent_limits"] == loaded["intent_limits"]
    assert legacy["allowed_actions"] == loaded["allowed_actions"]
