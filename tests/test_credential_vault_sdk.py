"""Invariant tests for credential vault SDK exports and pack layering.

Covers the design decisions made during the HashiCorp Vault integration:

1. SDK auto-registers all backends on import — consuming code (executor,
   packs) must never have to import intentframe_credentials directly just
   to make a backend available.

2. SDK re-exports all backend classes — packs must be able to reference
   KeyringVault / HashiCorpVault / EnvVault / ServiceVault via the SDK alone.

3. Pack layering — executor packs must not contain import statements that
   reach into intentframe_credentials directly. Only executor_sdk may do so.
   Mirrors the AST-based approach in test_boundary_imports.py.

4. create_credential_vault contract — config objects with each backend name
   that is registered produce a matching vault type without live services.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 1.  SDK import auto-registers every backend
# ---------------------------------------------------------------------------

def test_sdk_import_registers_all_backends():
    """Importing executor_sdk.services.credential_vault registers all four
    storage backends so config-driven startup never needs an explicit import."""
    import executor_sdk.services.credential_vault  # noqa: F401 (side-effect import)
    from intentframe_credentials.protocol import registered_backends

    required = {"keyring", "env", "hashicorp", "service"}
    missing = required - set(registered_backends())
    assert not missing, (
        f"Backends not auto-registered after SDK import: {missing}. "
        f"Registered: {registered_backends()}"
    )


# ---------------------------------------------------------------------------
# 2.  SDK __all__ re-exports concrete backend classes
# ---------------------------------------------------------------------------

def test_sdk_exports_all_backend_classes():
    import executor_sdk.services.credential_vault as cv

    required = {
        "CredentialVault",
        "KeyringVault",
        "HashiCorpVault",
        "EnvVault",
        "ServiceVault",
        "register_credential_vault",
        "create_credential_vault",
    }
    missing = required - set(cv.__all__)
    assert not missing, f"SDK __all__ is missing: {missing}"


def test_sdk_exported_names_are_actually_importable():
    """Each name in __all__ must be a real attribute, not just a string."""
    import executor_sdk.services.credential_vault as cv

    for name in cv.__all__:
        assert hasattr(cv, name), f"executor_sdk.services.credential_vault.{name} not found"


# ---------------------------------------------------------------------------
# 3.  Pack layering — AST check
# ---------------------------------------------------------------------------

def _collect_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _pack_violations(pack_root: Path) -> list[str]:
    """Return a list of files inside pack_root that import intentframe_credentials."""
    violations = []
    for path in sorted(pack_root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        for imported in _collect_imports(path):
            if imported.startswith("intentframe_credentials"):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported!r}")
    return violations


def test_macos_pack_does_not_import_credentials_directly():
    """The macOS executor pack must route through executor_sdk, not reach
    into intentframe_credentials.  See executor_sdk/services/credential_vault.py."""
    pack_root = REPO_ROOT / "intentframe_native_kit" / "intentframe_executor_pack_macos"
    if not pack_root.exists():
        pytest.skip("intentframe_native_kit/intentframe_executor_pack_macos not present")

    violations = _pack_violations(pack_root)
    assert not violations, (
        "Executor packs must not import intentframe_credentials directly. "
        "Use executor_sdk.services.credential_vault instead.\n"
        + "\n".join(violations)
    )


def test_future_packs_do_not_import_credentials_directly():
    """Scan all *_executor_pack_* directories in the repo root for the same
    layering violation so the rule holds for any pack added in future."""
    violations = []
    for pack_root in sorted(REPO_ROOT.glob("*_executor_pack_*")):
        if not pack_root.is_dir():
            continue
        for v in _pack_violations(pack_root):
            violations.append(v)

    assert not violations, (
        "Executor packs must not import intentframe_credentials directly.\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 4.  create_credential_vault contract
# ---------------------------------------------------------------------------

def _config(backend: str, **options) -> SimpleNamespace:
    return SimpleNamespace(backend=backend, options=options)


def test_create_credential_vault_env():
    from executor_sdk.services.credential_vault import create_credential_vault
    from intentframe_credentials.backends.env_backend import EnvVault

    vault = create_credential_vault(_config("env"))
    assert isinstance(vault, EnvVault)


def test_create_credential_vault_keyring():
    """KeyringVault is constructable without a real keyring present; it only
    imports keyring lazily at get/store time."""
    from executor_sdk.services.credential_vault import create_credential_vault
    from intentframe_credentials.backends.keyring_backend import KeyringVault

    vault = create_credential_vault(_config("keyring"))
    assert isinstance(vault, KeyringVault)


def test_create_credential_vault_hashicorp():
    """HashiCorpVault is instantiable with a mocked hvac client."""
    from executor_sdk.services.credential_vault import create_credential_vault
    from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault

    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    with patch("hvac.Client", return_value=mock_client):
        vault = create_credential_vault(_config("hashicorp", addr="http://v:8200", token="t", renew=False))
    assert isinstance(vault, HashiCorpVault)


def test_create_credential_vault_unknown_backend_raises():
    from executor_sdk.services.credential_vault import create_credential_vault
    from executor_sdk.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError, match="Unknown credential backend"):
        create_credential_vault(_config("does_not_exist"))


# ---------------------------------------------------------------------------
# 5.  KeychainVault alias in macOS pack resolves through SDK
# ---------------------------------------------------------------------------

def test_macos_pack_keychainvault_is_sdk_keyringvault():
    """KeychainVault in the macOS pack is the same class as KeyringVault in
    the SDK — no separate subclass, no credentials import."""
    macos_pack = REPO_ROOT / "intentframe_native_kit" / "intentframe_executor_pack_macos"
    if not macos_pack.exists():
        pytest.skip("intentframe_native_kit/intentframe_executor_pack_macos not present")

    from intentframe_native_kit.intentframe_executor_pack_macos.credential_vault import KeychainVault
    from executor_sdk.services.credential_vault import KeyringVault

    assert KeychainVault is KeyringVault, (
        "KeychainVault should be the same object as KeyringVault (aliased via SDK). "
        "It appears to have been re-imported from intentframe_credentials."
    )
