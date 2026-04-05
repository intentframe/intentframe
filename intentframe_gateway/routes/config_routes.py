"""App configuration routes — /config/*

Simple key-value preferences stored in SQLite (gateway.db).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/config", tags=["config"])

logger = logging.getLogger(__name__)


class ConfigValue(BaseModel):
    value: Any


@router.get("/")
async def get_all_config(request: Request):
    """Return all app preferences."""
    store = request.app.state.store
    return await store.config_get_all()


@router.get("/{key}")
async def get_config(request: Request, key: str):
    """Return a single preference value."""
    store = request.app.state.store
    value = await store.config_get(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Config key not found: {key}")
    return {"key": key, "value": value}


@router.put("/{key}")
async def set_config(request: Request, key: str, body: ConfigValue):
    """Set a preference value."""
    store = request.app.state.store
    await store.config_set(key, body.value)
    logger.info("App config set: %s", key)
    return {"key": key, "value": body.value}


@router.delete("/{key}")
async def delete_config(request: Request, key: str):
    """Remove a preference."""
    store = request.app.state.store
    deleted = await store.config_delete(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Config key not found: {key}")
    logger.info("App config deleted: %s", key)
    return {"key": key, "deleted": True}
