"""FastAPI credential vault service.

Designed to run on a Unix Domain Socket under the IntentFrame supervisor.
Provides CRUD for credentials (secret values stored in keyring, metadata
in SQLite) plus masked listing endpoints for the dashboard.

Startup::

    uvicorn intentframe_credentials.server:app --uds /path/to/credential-vault.sock
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException

from intentframe_credentials.metadata import MetadataStore
from intentframe_credentials.models import (
    CredentialRecord,
    MaskedSummary,
    StoreRequest,
    mask_value,
)
from intentframe_credentials.protocol import CredentialVault

logger = logging.getLogger(__name__)

# ── Module-level state (populated at lifespan) ───────────────────────────────

_vault: CredentialVault | None = None
_meta: MetadataStore | None = None


def _get_vault() -> CredentialVault:
    assert _vault is not None, "vault not initialised"
    return _vault


def _get_meta() -> MetadataStore:
    assert _meta is not None, "metadata store not initialised"
    return _meta


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ANN201
    """Initialise the keyring backend and metadata store on startup.

    If ``_vault`` / ``_meta`` are already set (e.g. by dev_server.py
    pre-seeding), they are kept as-is.
    """
    global _vault, _meta  # noqa: PLW0603

    if _vault is None:
        from intentframe_credentials.backends import keyring_backend as _kb  # noqa: F401
        from intentframe_credentials.protocol import create_vault

        _vault = create_vault("keyring")

    backend_name = type(_vault).__name__

    if _meta is None:
        _meta = MetadataStore()
        await _meta.open()

    logger.info("credential vault service ready (backend=%s)", backend_name)

    yield

    await _meta.close()
    logger.info("credential vault service stopped")


app = FastAPI(
    title="IntentFrame Credential Vault",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    meta = _get_meta()
    vault = _get_vault()
    count = await meta.count()
    return {"status": "ok", "backend": type(vault).__name__, "credential_count": count}


# ── CRUD ─────────────────────────────────────────────────────────────────────


@app.get("/v1/credentials/{namespace}/{key}")
async def get_credential(namespace: str, key: str) -> dict[str, str]:
    """Retrieve a credential value.  Trusted callers only (UDS)."""
    vault = _get_vault()
    meta = _get_meta()
    value = await vault.get(namespace, key)
    if value is None:
        raise HTTPException(status_code=404, detail="credential not found")
    await meta.touch_last_used(namespace, key)
    return {"value": value}


@app.head("/v1/credentials/{namespace}/{key}")
async def has_credential(namespace: str, key: str) -> None:
    """Check existence without retrieving the value."""
    vault = _get_vault()
    if not await vault.has(namespace, key):
        raise HTTPException(status_code=404, detail="credential not found")


@app.put("/v1/credentials/{namespace}/{key}")
async def store_credential(
    namespace: str,
    key: str,
    body: StoreRequest,
) -> dict[str, str]:
    """Store (or overwrite) a credential.  Never echoes the value back."""
    vault = _get_vault()
    meta = _get_meta()

    await vault.store(namespace, key, body.value)

    now = datetime.now(UTC)
    record = CredentialRecord(
        namespace=namespace,
        key=key,
        delivery_mode=body.delivery_mode,
        allowed_consumers=body.allowed_consumers,
        env_name=body.env_name,
        validator_id=body.validator_id,
        masked_preview=mask_value(body.value),
        created_at=now,
        updated_at=now,
    )
    await meta.upsert(record)

    logger.info("credential stored: namespace=%s key=%s", namespace, key)
    return {"status": "stored"}


@app.delete("/v1/credentials/{namespace}/{key}")
async def delete_credential(namespace: str, key: str) -> dict[str, str]:
    """Delete a credential from both keyring and metadata."""
    vault = _get_vault()
    meta = _get_meta()

    await vault.delete(namespace, key)
    await meta.delete(namespace, key)

    logger.info("credential deleted: namespace=%s key=%s", namespace, key)
    return {"status": "deleted"}


# ── Listing (masked, safe for dashboard) ─────────────────────────────────────


@app.get("/v1/credentials/{namespace}")
async def list_namespace(namespace: str) -> list[MaskedSummary]:
    """List masked summaries for all credentials in a namespace."""
    meta = _get_meta()
    return await meta.list_namespace_summaries(namespace)


@app.get("/v1/credentials")
async def list_all() -> list[MaskedSummary]:
    """List masked summaries for every credential in the vault."""
    meta = _get_meta()
    return await meta.list_all_summaries()


# ── Runtime-env query (used by supervisor spawn) ─────────────────────────────


@app.get("/v1/runtime-env")
async def list_runtime_env() -> list[dict[str, Any]]:
    """Return all runtime_env credentials (metadata only, no values).

    The supervisor uses this to know which env vars to inject, then
    fetches each value individually via ``GET /v1/credentials/{ns}/{key}``.
    """
    meta = _get_meta()
    records = await meta.list_runtime_env()
    return [
        {
            "namespace": r.namespace,
            "key": r.key,
            "env_name": r.env_name,
            "allowed_consumers": r.allowed_consumers,
        }
        for r in records
    ]
