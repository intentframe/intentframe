"""Credential vault proxy routes — /vault/*

Proxies all endpoints from credential-vault.sock.
The vault API lives under /v1/credentials on the backend;
the gateway re-mounts it at /vault/v1/credentials.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/vault", tags=["vault"])

_BACKEND = "credential-vault"


def _proxy(request: Request):
    return request.app.state.proxies[_BACKEND]


@router.get("/health")
async def vault_health(request: Request):
    return await _proxy(request).forward(request, "/health")


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "HEAD"],
)
async def vault_proxy(request: Request, path: str):
    backend_path = f"/{path}" if path else "/"
    return await _proxy(request).forward(request, backend_path)
