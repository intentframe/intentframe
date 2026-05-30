"""Tests for IF_VAULT_BACKEND env-driven backend selection in server.py lifespan.

Covers:
  - Default (no env var) selects 'keyring'
  - IF_VAULT_BACKEND=env selects EnvVault
  - IF_VAULT_BACKEND=hashicorp selects HashiCorpVault
  - Unknown backend name raises at startup (importlib.import_module fails)
  - vault.close() is called on shutdown when the backend exposes it
"""
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _reload_server():
    """Return a freshly-imported server module with cleared module-level state."""
    import intentframe_credentials.server as srv
    # Reset module-level singletons so lifespan starts clean each time
    srv._vault = None
    srv._meta = None
    return srv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meta_mock():
    meta = MagicMock()
    meta.open = AsyncMock()
    meta.close = AsyncMock()
    meta.count = AsyncMock(return_value=0)
    return meta


class DummyVault:
    async def get(self, namespace: str, key: str) -> str | None:
        return None

    async def store(self, namespace: str, key: str, value: str) -> None:
        return None

    async def delete(self, namespace: str, key: str) -> None:
        return None

    async def has(self, namespace: str, key: str) -> bool:
        return False

    async def list_keys(self, namespace: str) -> list[str]:
        return []


class DummyClosableVault(DummyVault):
    latest: "DummyClosableVault | None" = None

    def __init__(self) -> None:
        self.closed = False
        type(self).latest = self

    async def close(self) -> None:
        self.closed = True


# ===========================================================================
# Backend selection from IF_VAULT_BACKEND
# ===========================================================================

class TestBackendSelection:
    _CREATE_VAULT = "intentframe_credentials.server.create_vault"
    _IMPORT_MODULE = "importlib.import_module"

    async def test_default_selects_keyring(self, monkeypatch):
        monkeypatch.delenv("IF_VAULT_BACKEND", raising=False)
        srv = _reload_server()
        meta = _make_meta_mock()

        with patch.object(srv, "MetadataStore", return_value=meta), \
             patch.object(srv, "create_vault", return_value=DummyVault()) as mock_create, \
             patch(self._IMPORT_MODULE) as mock_import:
            async with srv.lifespan(None):
                pass

        mock_import.assert_called_once_with(
            "intentframe_credentials.backends.keyring_backend"
        )
        mock_create.assert_called_once_with("keyring")
        assert isinstance(srv._vault, DummyVault)

    async def test_env_var_selects_env_backend(self, monkeypatch):
        monkeypatch.setenv("IF_VAULT_BACKEND", "env")
        srv = _reload_server()
        meta = _make_meta_mock()

        with patch.object(srv, "MetadataStore", return_value=meta), \
             patch.object(srv, "create_vault", return_value=DummyVault()) as mock_create, \
             patch(self._IMPORT_MODULE) as mock_import:
            async with srv.lifespan(None):
                pass

        mock_import.assert_called_once_with(
            "intentframe_credentials.backends.env_backend"
        )
        mock_create.assert_called_once_with("env")
        assert isinstance(srv._vault, DummyVault)

    async def test_env_var_selects_hashicorp_backend(self, monkeypatch):
        monkeypatch.setenv("IF_VAULT_BACKEND", "hashicorp")
        srv = _reload_server()
        meta = _make_meta_mock()

        with patch.object(srv, "MetadataStore", return_value=meta), \
             patch.object(srv, "create_vault", return_value=DummyVault()) as mock_create, \
             patch(self._IMPORT_MODULE) as mock_import:
            async with srv.lifespan(None):
                pass

        mock_import.assert_called_once_with(
            "intentframe_credentials.backends.hashicorp_backend"
        )
        mock_create.assert_called_once_with("hashicorp")
        assert isinstance(srv._vault, DummyVault)

    async def test_pre_set_vault_is_not_replaced(self, monkeypatch):
        """If _vault is already set (e.g. by dev_server pre-seeding) lifespan
        must leave it untouched and not call create_vault."""
        from intentframe_credentials.backends.env_backend import EnvVault
        import intentframe_credentials.server as srv
        srv._vault = EnvVault()
        srv._meta = None

        meta = _make_meta_mock()
        with patch.object(srv, "MetadataStore", return_value=meta), \
             patch.object(srv, "create_vault") as mock_create:
            async with srv.lifespan(None):
                pass

        mock_create.assert_not_called()
        srv._vault = None  # restore clean state

    async def test_unknown_backend_raises_on_import(self, monkeypatch):
        monkeypatch.setenv("IF_VAULT_BACKEND", "does_not_exist")
        srv = _reload_server()
        meta = _make_meta_mock()

        with patch("intentframe_credentials.server.MetadataStore", return_value=meta), \
             pytest.raises(ModuleNotFoundError):
            async with srv.lifespan(None):
                pass


# ===========================================================================
# vault.close() called on shutdown
# ===========================================================================

class TestShutdownClose:
    _CREATE_VAULT = "intentframe_credentials.server.create_vault"

    async def test_close_called_when_vault_has_close(self, monkeypatch):
        monkeypatch.setenv("IF_VAULT_BACKEND", "env")
        srv = _reload_server()
        meta = _make_meta_mock()

        DummyClosableVault.latest = None
        vault = DummyClosableVault()

        with patch.object(srv, "MetadataStore", return_value=meta), \
             patch.object(srv, "create_vault", return_value=vault), \
             patch("importlib.import_module"):
            async with srv.lifespan(None):
                pass

        assert DummyClosableVault.latest is not None
        assert DummyClosableVault.latest.closed is True

    async def test_no_error_when_vault_has_no_close(self, monkeypatch):
        """Keyring/env backends don't have close(); lifespan must not crash."""
        monkeypatch.setenv("IF_VAULT_BACKEND", "env")
        srv = _reload_server()
        meta = _make_meta_mock()

        with patch.object(srv, "MetadataStore", return_value=meta), \
             patch.object(srv, "create_vault", return_value=DummyVault()), \
             patch("importlib.import_module"):
            async with srv.lifespan(None):
                pass
