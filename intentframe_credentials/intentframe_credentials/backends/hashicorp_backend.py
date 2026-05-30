"""HashiCorp Vault (KV v2) credential backend — headless-friendly.

The OS keyring backend does not work on a headless cloud server (no
Keychain / GNOME Keyring daemon).  This backend stores secrets in a
HashiCorp Vault server over its HTTP API, so IntentFrame can run on any
cloud, on-prem box, or Kubernetes cluster that can reach a Vault.

Configuration is read from environment variables first — so a deployer
only needs to inject env vars, no code changes — with constructor
``options`` taking precedence for tests and programmatic embedding.

    VAULT_ADDR        e.g. https://vault.mycorp.com:8200   (required)
    VAULT_TOKEN       static token                          (auth option A)
    VAULT_ROLE_ID     AppRole role_id                       (auth option B)
    VAULT_SECRET_ID   AppRole secret_id                     (auth option B)
    VAULT_NAMESPACE   Vault Enterprise namespace            (optional)
    VAULT_KV_MOUNT    KV v2 mount point, default "secret"   (optional)
    VAULT_PATH_PREFIX path prefix, default "intentframe"    (optional)

Storage layout
--------------
Each IntentFrame *namespace* maps to one KV v2 secret at
``<prefix>/<namespace>`` and each *key* is a field within that secret.
This mirrors the grouping used by the keyring backend and lets
``list_keys`` work natively (KV v2 returns all fields in one read).

All ``hvac`` calls are dispatched via ``asyncio.to_thread`` because the
client is synchronous and performs blocking network I/O.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

from intentframe_credentials.exceptions import (
    BackendUnavailableError,
    CredentialDeleteError,
    CredentialStoreError,
)
from intentframe_credentials.protocol import CredentialVault, register_backend

logger = logging.getLogger(__name__)

__all__ = ["HashiCorpVault"]

_DEFAULT_MOUNT = "secret"
_DEFAULT_PREFIX = "intentframe"

# Renew once at least this fraction of the token's TTL has elapsed.
_RENEW_AT_FRACTION = 0.5
# Floor / ceiling so we neither hammer Vault nor sleep forever.
_MIN_RENEW_SLEEP = 5.0
_RENEW_BACKOFF = 10.0


def _opt(options: dict[str, Any], key: str, env: str, default: str | None = None) -> str | None:
    """Resolve a setting: constructor option > env var > default."""
    value = options.get(key)
    if value is not None:
        return str(value)
    return os.environ.get(env, default)


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


class HashiCorpVault(CredentialVault):
    """Credential vault backed by a HashiCorp Vault KV v2 secrets engine."""

    def __init__(self, **options: Any) -> None:
        try:
            import hvac
        except ImportError as exc:  # pragma: no cover - import guard
            raise BackendUnavailableError(
                "hvac package required for the hashicorp backend. "
                "Install with: pip install 'intentframe-credentials[hashicorp]'",
            ) from exc

        addr = _opt(options, "addr", "VAULT_ADDR")
        if not addr:
            raise BackendUnavailableError(
                "VAULT_ADDR not configured for the hashicorp backend",
            )

        self._mount = _opt(options, "kv_mount", "VAULT_KV_MOUNT", _DEFAULT_MOUNT) or _DEFAULT_MOUNT
        self._prefix = (
            _opt(options, "path_prefix", "VAULT_PATH_PREFIX", _DEFAULT_PREFIX) or _DEFAULT_PREFIX
        ).strip("/")
        vault_ns = _opt(options, "namespace", "VAULT_NAMESPACE")
        verify = options.get("verify", True)

        # Auth params are kept so the renewal loop can re-login on expiry.
        self._token = _opt(options, "token", "VAULT_TOKEN")
        self._role_id = _opt(options, "role_id", "VAULT_ROLE_ID")
        self._secret_id = _opt(options, "secret_id", "VAULT_SECRET_ID")

        self._client = hvac.Client(url=addr, namespace=vault_ns, verify=verify)
        self._authenticate()

        # Token renewal background task (lazily started on first async call,
        # since __init__ runs synchronously without a running event loop).
        self._renew_enabled = _as_bool(_opt(options, "renew", "VAULT_RENEW", "true"))
        self._renew_task: asyncio.Task[None] | None = None

        logger.info(
            "hashicorp vault backend ready (mount=%s prefix=%s renew=%s)",
            self._mount,
            self._prefix,
            self._renew_enabled,
        )

    # -- auth --

    def _authenticate(self) -> None:
        if self._token:
            self._client.token = self._token
        elif self._role_id and self._secret_id:
            self._client.auth.approle.login(
                role_id=self._role_id,
                secret_id=self._secret_id,
            )
        else:
            raise BackendUnavailableError(
                "No Vault auth configured: set VAULT_TOKEN or "
                "VAULT_ROLE_ID + VAULT_SECRET_ID",
            )

        if not self._client.is_authenticated():
            raise BackendUnavailableError("Vault authentication failed")

    def _can_relogin(self) -> bool:
        """AppRole creds let us mint a fresh token; a static token cannot."""
        return bool(self._role_id and self._secret_id)

    # -- token renewal (hvac does NOT do this automatically) --

    def _ensure_renewal(self) -> None:
        """Start the renewal loop once, bound to the running event loop."""
        if not self._renew_enabled or self._renew_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._renew_task = loop.create_task(self._renewal_loop())

    async def _renewal_loop(self) -> None:
        """Keep the Vault token alive for the life of the process.

        hvac only exposes one-shot ``renew_self`` / ``login`` calls, so we
        schedule them here:  sleep until ~half the TTL has elapsed, then
        renew.  If the token is not renewable (or renewal fails) fall back
        to an AppRole re-login.  A static token with no AppRole and no TTL
        (e.g. a root/dev token) needs nothing, so the loop exits cleanly.
        """
        while True:
            try:
                info = await asyncio.to_thread(self._lookup_self)
                ttl = int(info.get("ttl", 0) or 0)
                renewable = bool(info.get("renewable", False))

                if ttl <= 0:
                    # No expiry (root/dev token). Nothing to renew.
                    logger.info("vault token has no TTL; renewal loop stopping")
                    return

                await asyncio.sleep(max(ttl * _RENEW_AT_FRACTION, _MIN_RENEW_SLEEP))

                if renewable:
                    await asyncio.to_thread(self._client.auth.token.renew_self)
                    logger.debug("renewed vault token")
                elif self._can_relogin():
                    await asyncio.to_thread(self._relogin)
                    logger.debug("re-logged into vault (token not renewable)")
                else:
                    logger.warning(
                        "vault token not renewable and no AppRole configured; "
                        "renewal loop stopping",
                    )
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network/runtime dependent
                logger.warning("vault token renewal failed: %s", exc)
                if not self._can_relogin():
                    logger.error("vault token renewal unrecoverable; stopping loop")
                    return
                try:
                    await asyncio.to_thread(self._relogin)
                    logger.info("recovered vault session via AppRole re-login")
                except Exception as relogin_exc:  # pragma: no cover
                    logger.error("vault re-login failed: %s", relogin_exc)
                    await asyncio.sleep(_RENEW_BACKOFF)

    def _lookup_self(self) -> dict[str, Any]:
        return self._client.auth.token.lookup_self()["data"]

    async def token_info(self) -> dict[str, Any]:
        """Return Vault's view of the current token (``lookup-self`` data).

        Diagnostic helper for health checks and for observing the renewal
        loop — exposes ``ttl``, ``renewable``, ``policies``, etc.  Never
        includes the token value itself.
        """
        return await asyncio.to_thread(self._lookup_self)

    def _relogin(self) -> None:
        self._client.auth.approle.login(
            role_id=self._role_id,
            secret_id=self._secret_id,
        )

    # -- helpers --

    def _path(self, namespace: str) -> str:
        """Map an IntentFrame namespace to a KV v2 secret path."""
        return f"{self._prefix}/{namespace}"

    def _read_fields(self, namespace: str) -> dict[str, str]:
        """Return all fields of a namespace secret, or ``{}`` if absent.

        Runs synchronously — callers must wrap in ``asyncio.to_thread``.
        """
        import hvac

        try:
            resp = self._client.secrets.kv.v2.read_secret_version(
                path=self._path(namespace),
                mount_point=self._mount,
                raise_on_deleted_version=True,
            )
        except hvac.exceptions.InvalidPath:
            return {}
        return dict(resp["data"]["data"])

    def _write_fields(self, namespace: str, fields: dict[str, str]) -> None:
        """Overwrite a namespace secret with *fields* (sync)."""
        self._client.secrets.kv.v2.create_or_update_secret(
            path=self._path(namespace),
            secret=fields,
            mount_point=self._mount,
        )

    # -- CredentialVault interface --

    async def get(self, namespace: str, key: str) -> str | None:
        self._ensure_renewal()
        fields = await asyncio.to_thread(self._read_fields, namespace)
        return fields.get(key)

    async def store(self, namespace: str, key: str, value: str) -> None:
        self._ensure_renewal()

        def _store() -> None:
            fields = self._read_fields(namespace)
            fields[key] = value
            self._write_fields(namespace, fields)

        try:
            await asyncio.to_thread(_store)
            logger.debug("stored credential: namespace=%s key=%s", namespace, key)
        except Exception as exc:
            raise CredentialStoreError(
                f"failed to store credential in Vault: {exc}",
            ) from exc

    async def delete(self, namespace: str, key: str) -> None:
        self._ensure_renewal()

        def _delete() -> None:
            fields = self._read_fields(namespace)
            if key not in fields:
                return
            fields.pop(key, None)
            if fields:
                self._write_fields(namespace, fields)
            else:
                # No fields left — remove the secret entirely.
                self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=self._path(namespace),
                    mount_point=self._mount,
                )

        try:
            await asyncio.to_thread(_delete)
            logger.debug("deleted credential: namespace=%s key=%s", namespace, key)
        except Exception as exc:
            raise CredentialDeleteError(
                f"failed to delete credential from Vault: {exc}",
            ) from exc

    async def has(self, namespace: str, key: str) -> bool:
        return (await self.get(namespace, key)) is not None

    async def list_keys(self, namespace: str) -> list[str]:
        self._ensure_renewal()
        fields = await asyncio.to_thread(self._read_fields, namespace)
        return list(fields.keys())

    async def close(self) -> None:
        """Cancel the renewal task.  Called by the service on shutdown."""
        if self._renew_task is not None:
            self._renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._renew_task
            self._renew_task = None


register_backend("hashicorp", HashiCorpVault)
