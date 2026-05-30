"""Unit tests for HashiCorpVault — no live Vault required.

All hvac I/O is replaced with a MagicMock so these run anywhere, including
CI with no VAULT_ADDR. They cover:

  - Init / auth:   missing addr, missing auth, token vs AppRole precedence,
                   env-var vs option resolution, failed is_authenticated
  - Config:        mount / prefix / renew from env and from options
  - Path mapping:  namespace → KV v2 path
  - CRUD:          store/get/has/delete/list_keys via mocked _read_fields
  - Error wrapping: CredentialStoreError / CredentialDeleteError on failure
  - Renewal loop:  no-TTL exits immediately, renewable token calls renew_self,
                   non-renewable + AppRole calls relogin, close() cancels task
  - close():       idempotent, does nothing when no task is running
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from intentframe_credentials.exceptions import (
    BackendUnavailableError,
    CredentialDeleteError,
    CredentialStoreError,
)

_REAL_ASYNCIO_SLEEP = asyncio.sleep


# ---------------------------------------------------------------------------
# Helpers — build a HashiCorpVault with a fully-mocked hvac.Client
# ---------------------------------------------------------------------------

def _make_vault(
    *,
    addr: str = "http://vault:8200",
    token: str = "tok",
    is_authenticated: bool = True,
    renew: bool = False,       # off by default in unit tests — not testing timing
    env: dict[str, str] | None = None,
    **extra_options,
) -> tuple["HashiCorpVault", MagicMock]:  # type: ignore[name-defined]
    """Return (vault, mock_client) with hvac patched out.

    We clear every VAULT_* env var so ambient shell state (e.g. from
    vault_dev_setup.sh) never bleeds into unit tests.
    """
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = is_authenticated

    # Wipe VAULT_* from the process env for the duration of the call so
    # tests are hermetic regardless of what vault_dev_setup.sh exported.
    clean_env = {
        k: v for k, v in __import__("os").environ.items()
        if not k.startswith("VAULT_")
    }
    if env:
        clean_env.update(env)
    with patch.dict("os.environ", clean_env, clear=True), \
         patch("hvac.Client", return_value=mock_client):
        from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
        vault = HashiCorpVault(addr=addr, token=token, renew=renew, **extra_options)

    # Re-attach mock so callers can configure return values after construction
    vault._client = mock_client
    return vault, mock_client


# Helper: make asyncio.to_thread run its callable synchronously so unit tests
# don't need a real thread pool or worry about thread-vs-event-loop ordering.
async def _sync_to_thread(func, *args, **kwargs):
    return func(*args, **kwargs)


# ===========================================================================
# Init / auth
# ===========================================================================

class TestInit:
    def test_missing_addr_raises(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        with patch("hvac.Client"):
            from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
            with pytest.raises(BackendUnavailableError, match="VAULT_ADDR not configured"):
                HashiCorpVault(token="tok")

    def test_no_auth_raises(self, monkeypatch):
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
        monkeypatch.delenv("VAULT_SECRET_ID", raising=False)
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        with patch("hvac.Client", return_value=mock_client):
            from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
            with pytest.raises(BackendUnavailableError, match="No Vault auth configured"):
                HashiCorpVault(addr="http://vault:8200")

    def test_token_sets_client_token(self):
        vault, client = _make_vault(token="my-token")
        assert client.token == "my-token"

    def test_token_takes_precedence_over_approle(self):
        """VAULT_TOKEN wins even when role_id + secret_id are also provided."""
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        with patch("hvac.Client", return_value=mock_client):
            from importlib import reload
            import intentframe_credentials.backends.hashicorp_backend as mod
            vault = mod.HashiCorpVault(
                addr="http://v:8200",
                token="static-tok",
                role_id="rid",
                secret_id="sid",
                renew=False,
            )
        # AppRole login must NOT have been called
        mock_client.auth.approle.login.assert_not_called()
        assert mock_client.token == "static-tok"

    def test_approle_login_called_when_no_token(self, monkeypatch):
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        with patch("hvac.Client", return_value=mock_client):
            from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
            HashiCorpVault(addr="http://v:8200", role_id="rid", secret_id="sid", renew=False)
        mock_client.auth.approle.login.assert_called_once_with(role_id="rid", secret_id="sid")

    def test_failed_is_authenticated_raises(self):
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = False
        with patch("hvac.Client", return_value=mock_client):
            from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
            with pytest.raises(BackendUnavailableError, match="authentication failed"):
                HashiCorpVault(addr="http://v:8200", token="tok", renew=False)

    def test_can_relogin_true_when_approle(self):
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        with patch("hvac.Client", return_value=mock_client):
            from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
            v = HashiCorpVault(addr="http://v:8200", role_id="rid", secret_id="sid", renew=False)
        assert v._can_relogin() is True

    def test_can_relogin_false_when_static_token_only(self):
        vault, _ = _make_vault()
        assert vault._can_relogin() is False


class TestConfig:
    def test_default_mount_and_prefix(self):
        vault, _ = _make_vault()
        assert vault._mount == "secret"
        assert vault._prefix == "intentframe"

    def test_custom_mount_and_prefix_via_options(self):
        vault, _ = _make_vault(kv_mount="kv", path_prefix="myapp")
        assert vault._mount == "kv"
        assert vault._prefix == "myapp"

    def test_prefix_strips_leading_slash(self):
        vault, _ = _make_vault(path_prefix="/myapp/")
        assert vault._prefix == "myapp"

    def test_mount_from_env(self, monkeypatch):
        vault, _ = _make_vault(env={"VAULT_KV_MOUNT": "kvv2"})
        assert vault._mount == "kvv2"

    def test_option_overrides_env(self, monkeypatch):
        vault, _ = _make_vault(
            kv_mount="from-option",
            env={"VAULT_KV_MOUNT": "from-env"},
        )
        assert vault._mount == "from-option"

    def test_renew_disabled_via_option(self):
        vault, _ = _make_vault(renew=False)
        assert vault._renew_enabled is False

    def test_renew_disabled_via_env(self, monkeypatch):
        vault, _ = _make_vault(env={"VAULT_RENEW": "false"})
        assert vault._renew_enabled is False

    def test_path_mapping(self):
        vault, _ = _make_vault(path_prefix="myapp")
        assert vault._path("email.u@g.com") == "myapp/email.u@g.com"


# ===========================================================================
# CRUD operations — _read_fields / _write_fields mocked
# ===========================================================================

class TestCRUD:
    def _vault_with_storage(self, initial: dict | None = None):
        """Return a vault whose KV storage is backed by an in-memory dict."""
        vault, client = _make_vault(renew=False)
        store: dict[str, dict[str, str]] = {}
        if initial:
            store.update(initial)

        import hvac as _hvac

        def read(path, mount_point, raise_on_deleted_version):
            if path not in store:
                raise _hvac.exceptions.InvalidPath
            return {"data": {"data": dict(store[path])}}

        def write(path, secret, mount_point):
            store[path] = dict(secret)

        def delete_meta(path, mount_point):
            store.pop(path, None)

        client.secrets.kv.v2.read_secret_version.side_effect = read
        client.secrets.kv.v2.create_or_update_secret.side_effect = write
        client.secrets.kv.v2.delete_metadata_and_all_versions.side_effect = delete_meta
        return vault, store

    async def test_store_and_get(self):
        vault, _ = self._vault_with_storage()
        await vault.store("ns", "key", "value")
        assert await vault.get("ns", "key") == "value"

    async def test_get_missing_returns_none(self):
        vault, _ = self._vault_with_storage()
        assert await vault.get("ns", "missing") is None

    async def test_store_multiple_keys_same_namespace(self):
        vault, store = self._vault_with_storage()
        await vault.store("ns", "a", "1")
        await vault.store("ns", "b", "2")
        keys = await vault.list_keys("ns")
        assert set(keys) == {"a", "b"}

    async def test_overwrite_preserves_siblings(self):
        vault, _ = self._vault_with_storage()
        await vault.store("ns", "a", "old")
        await vault.store("ns", "b", "sibling")
        await vault.store("ns", "a", "new")
        assert await vault.get("ns", "a") == "new"
        assert await vault.get("ns", "b") == "sibling"

    async def test_has_present(self):
        vault, _ = self._vault_with_storage()
        await vault.store("ns", "k", "v")
        assert await vault.has("ns", "k") is True

    async def test_has_absent(self):
        vault, _ = self._vault_with_storage()
        assert await vault.has("ns", "nope") is False

    async def test_delete_removes_field(self):
        vault, _ = self._vault_with_storage()
        await vault.store("ns", "a", "1")
        await vault.store("ns", "b", "2")
        await vault.delete("ns", "a")
        assert await vault.get("ns", "a") is None
        assert await vault.get("ns", "b") == "2"

    async def test_delete_last_field_removes_secret(self):
        vault, store = self._vault_with_storage()
        await vault.store("ns", "only", "v")
        await vault.delete("ns", "only")
        assert "intentframe/ns" not in store

    async def test_delete_missing_is_noop(self):
        vault, _ = self._vault_with_storage()
        await vault.delete("ns", "ghost")   # must not raise

    async def test_list_keys_empty(self):
        vault, _ = self._vault_with_storage()
        assert await vault.list_keys("ns") == []


# ===========================================================================
# Error wrapping
# ===========================================================================

class TestErrorWrapping:
    async def test_store_wraps_exception_as_credential_store_error(self):
        vault, client = _make_vault(renew=False)
        import hvac
        client.secrets.kv.v2.read_secret_version.side_effect = hvac.exceptions.InvalidPath
        client.secrets.kv.v2.create_or_update_secret.side_effect = RuntimeError("network down")
        with pytest.raises(CredentialStoreError, match="network down"):
            await vault.store("ns", "k", "v")

    async def test_delete_wraps_exception_as_credential_delete_error(self):
        vault, client = _make_vault(renew=False)
        import hvac
        # Simulate a secret that exists but delete_metadata blows up
        client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"only": "val"}}
        }
        client.secrets.kv.v2.delete_metadata_and_all_versions.side_effect = RuntimeError("boom")
        with pytest.raises(CredentialDeleteError, match="boom"):
            await vault.delete("ns", "only")


# ===========================================================================
# Renewal loop state machine
# ===========================================================================

class TestRenewalLoop:
    """Tests for _renewal_loop without real sleeps, threads, or network.

    Strategy:
      - Patch asyncio.to_thread with _sync_to_thread so _lookup_self and
        renew_self run synchronously in the event loop.
      - Patch asyncio.sleep with a real asyncio.sleep(0) so the event loop
        still turns between iterations without actually waiting.
      - Control loop exit by making _lookup_self return ttl=0 after N calls.
    """

    def _make_approle_vault(self):
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        clean_env = {
            k: v for k, v in __import__("os").environ.items()
            if not k.startswith("VAULT_")
        }
        with patch.dict("os.environ", clean_env, clear=True), \
             patch("hvac.Client", return_value=mock_client):
            from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault
            vault = HashiCorpVault(
                addr="http://v:8200", role_id="rid", secret_id="sid", renew=True,
            )
        vault._client = mock_client
        return vault, mock_client

    async def test_no_ttl_loop_exits_immediately(self):
        vault, _ = _make_vault(renew=True)
        vault._lookup_self = lambda: {"ttl": 0, "renewable": False}

        # sleep should never be called — loop exits before reaching it
        async def fail_if_called(t):
            raise AssertionError("asyncio.sleep should not be called for ttl=0")

        with patch("asyncio.to_thread", side_effect=_sync_to_thread), \
             patch("intentframe_credentials.backends.hashicorp_backend.asyncio.sleep",
                   side_effect=fail_if_called):
            task = asyncio.create_task(vault._renewal_loop())
            await asyncio.wait_for(task, timeout=1.0)
            assert task.done() and not task.cancelled()

    async def test_renewable_token_calls_renew_self(self):
        vault, client = _make_vault(renew=True)
        renew_calls: list[str] = []
        call_count = 0

        def lookup():
            nonlocal call_count
            call_count += 1
            # After one renewal, return ttl=0 to stop the loop
            return {"ttl": 0 if call_count > 1 else 10, "renewable": True}

        vault._lookup_self = lookup
        client.auth.token.renew_self.side_effect = lambda: renew_calls.append("renew")

        async def fast_sleep(t):
            await _REAL_ASYNCIO_SLEEP(0)

        with patch("asyncio.to_thread", side_effect=_sync_to_thread), \
             patch("intentframe_credentials.backends.hashicorp_backend.asyncio.sleep",
                   side_effect=fast_sleep):
            task = asyncio.create_task(vault._renewal_loop())
            await asyncio.wait_for(task, timeout=1.0)

        assert renew_calls, "expected renew_self to be called at least once"

    async def test_non_renewable_with_approle_calls_relogin(self):
        """Token not renewable + AppRole → _relogin, never renew_self."""
        vault, client = self._make_approle_vault()
        relogins: list[str] = []
        call_count = 0

        def lookup():
            nonlocal call_count
            call_count += 1
            return {"ttl": 0 if call_count > 1 else 10, "renewable": False}

        vault._lookup_self = lookup
        vault._relogin = lambda: relogins.append("relogin")

        async def fast_sleep(t):
            await _REAL_ASYNCIO_SLEEP(0)

        with patch("asyncio.to_thread", side_effect=_sync_to_thread), \
             patch("intentframe_credentials.backends.hashicorp_backend.asyncio.sleep",
                   side_effect=fast_sleep):
            task = asyncio.create_task(vault._renewal_loop())
            await asyncio.wait_for(task, timeout=1.0)

        assert relogins, "expected _relogin to be called"
        client.auth.token.renew_self.assert_not_called()

    async def test_non_renewable_no_approle_loop_stops(self):
        """Token not renewable + no AppRole → loop exits cleanly."""
        vault, _ = _make_vault(renew=True)  # no role_id/secret_id
        vault._lookup_self = lambda: {"ttl": 10, "renewable": False}

        async def fast_sleep(t):
            await _REAL_ASYNCIO_SLEEP(0)

        with patch("asyncio.to_thread", side_effect=_sync_to_thread), \
             patch("intentframe_credentials.backends.hashicorp_backend.asyncio.sleep",
                   side_effect=fast_sleep):
            task = asyncio.create_task(vault._renewal_loop())
            await asyncio.wait_for(task, timeout=1.0)
            assert task.done() and not task.cancelled()

    async def test_close_cancels_renewal_task(self):
        vault, _ = _make_vault(renew=True)
        sentinel = asyncio.Event()

        async def long_loop():
            sentinel.set()
            await asyncio.sleep(9999)

        vault._renew_task = asyncio.create_task(long_loop())
        await sentinel.wait()

        await vault.close()
        assert vault._renew_task is None

    async def test_close_is_idempotent_when_no_task(self):
        vault, _ = _make_vault(renew=False)
        await vault.close()   # must not raise

    async def test_ensure_renewal_starts_task_once(self):
        vault, _ = _make_vault(renew=True)
        vault._lookup_self = lambda: {"ttl": 0, "renewable": False}

        vault._ensure_renewal()
        task1 = vault._renew_task
        vault._ensure_renewal()   # second call — must not replace the task
        task2 = vault._renew_task
        assert task1 is task2
        await vault.close()

    async def test_ensure_renewal_no_op_when_disabled(self):
        vault, _ = _make_vault(renew=False)
        vault._ensure_renewal()
        assert vault._renew_task is None
