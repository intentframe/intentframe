"""Policy registry proxy routes — /policies (read-only)

Only GET endpoints are exposed. Policies are seeded at bootstrap and
cannot be modified through the gateway.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/policies", tags=["policies"])

_BACKEND = "policy-registry"


def _proxy(request: Request):
    return request.app.state.proxies[_BACKEND]


@router.get("/health")
async def policies_health(request: Request):
    return await _proxy(request).forward(request, "/health")


@router.get("/{path:path}")
async def policies_read(request: Request, path: str):
    backend_path = f"/policies/{path}" if path else "/policies"
    return await _proxy(request).forward(request, backend_path)


@router.get("/")
async def policies_root(request: Request):
    return await _proxy(request).forward(request, "/policies")
