"""Audit proxy routes — /audit/*

Proxies the audit endpoints from intentframe-core (intentframe.sock).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/audit", tags=["audit"])

_BACKEND = "intentframe-core"


def _proxy(request: Request):
    return request.app.state.proxies[_BACKEND]


@router.get("/")
async def get_audit(request: Request):
    return await _proxy(request).forward(request, "/audit")

