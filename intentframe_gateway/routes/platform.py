"""Platform server proxy routes — /platform/*

Read-only proxy to platform.sock (the Swift macos-appkit-server).
The frontend uses these to display server status and TCC permissions.
Execute/rollback are handled directly by the executor via UDS.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/platform", tags=["platform"])

_BACKEND = "platform-server"


def _proxy(request: Request):
    return request.app.state.proxies[_BACKEND]


@router.get("/health")
async def platform_health(request: Request):
    return await _proxy(request).forward(request, "/health")


@router.get("/permissions")
async def platform_permissions(request: Request):
    return await _proxy(request).forward(request, "/permissions")
