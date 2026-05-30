"""Integration tests for the HashiCorp Vault backend.

These tests talk to a *real* Vault server and are skipped unless
``VAULT_ADDR`` is set in the environment.  Spin up a dev Vault first::

    docker run -d --name vault-dev --cap-add=IPC_LOCK -p 8200:8200 \
        -e VAULT_DEV_ROOT_TOKEN_ID=dev-root-token hashicorp/vault:latest

    export VAULT_ADDR=http://127.0.0.1:8200
    export VAULT_TOKEN=dev-root-token
    uv run pytest tests/test_hashicorp_backend.py -v

Without ``VAULT_ADDR`` the whole module is skipped, so CI stays green
on machines that have no Vault.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("VAULT_ADDR"),
    reason="VAULT_ADDR not set — skipping live HashiCorp Vault integration tests",
)


@pytest.fixture
def vault():
    from intentframe_credentials.backends.hashicorp_backend import HashiCorpVault

    # Disable the renewal loop in tests — a dev/root token has no TTL and
    # we are not exercising long-running behaviour here.
    return HashiCorpVault(renew=False)


@pytest.fixture
def namespace() -> str:
    # Unique per test run so parallel/repeated runs never collide.
    return f"test.{uuid.uuid4().hex[:12]}"


async def test_store_and_get(vault, namespace):
    await vault.store(namespace, "password", "hunter2")
    assert await vault.get(namespace, "password") == "hunter2"


async def test_get_missing_returns_none(vault, namespace):
    assert await vault.get(namespace, "nope") is None


async def test_has(vault, namespace):
    assert await vault.has(namespace, "token") is False
    await vault.store(namespace, "token", "abc")
    assert await vault.has(namespace, "token") is True


async def test_multiple_keys_in_one_namespace(vault, namespace):
    await vault.store(namespace, "username", "user@example.com")
    await vault.store(namespace, "password", "s3cret")
    keys = await vault.list_keys(namespace)
    assert set(keys) == {"username", "password"}


async def test_overwrite_preserves_other_fields(vault, namespace):
    await vault.store(namespace, "username", "user@example.com")
    await vault.store(namespace, "password", "first")
    await vault.store(namespace, "password", "second")
    assert await vault.get(namespace, "password") == "second"
    assert await vault.get(namespace, "username") == "user@example.com"


async def test_delete_one_field_keeps_others(vault, namespace):
    await vault.store(namespace, "username", "user@example.com")
    await vault.store(namespace, "password", "s3cret")
    await vault.delete(namespace, "password")
    assert await vault.get(namespace, "password") is None
    assert await vault.get(namespace, "username") == "user@example.com"


async def test_delete_last_field_removes_secret(vault, namespace):
    await vault.store(namespace, "only", "value")
    await vault.delete(namespace, "only")
    assert await vault.list_keys(namespace) == []


async def test_delete_missing_is_noop(vault, namespace):
    # Should not raise even though nothing exists.
    await vault.delete(namespace, "ghost")
