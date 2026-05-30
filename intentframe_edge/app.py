"""IntentFrame Edge FastAPI app — path-routes HTTP to backend UDS sockets.

    GET  /health                       → edge + backend health summary
    *    /policies*                    → policy-registry.sock
    *    /workspaces*                   → resource-registry.sock
    *    /handshake /process /audit*    → intentframe.sock
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from intentframe_edge.config import EdgeConfig, load_edge_config
from intentframe_proxy import UDSProxy

logger = logging.getLogger("intentframe.edge")

# Core /process can run for minutes; registries are quick.
_CORE_TIMEOUT = 120.0
_DEFAULT_TIMEOUT = 30.0


def create_app(config: EdgeConfig | None = None) -> FastAPI:
    config = config or load_edge_config()

    proxies: dict[str, UDSProxy] = {}
    # (prefix, proxy) pairs, matched longest-prefix-first.
    routes: list[tuple[str, UDSProxy]] = []
    for backend in config.backends:
        timeout = _CORE_TIMEOUT if backend.name == "intentframe-core" else _DEFAULT_TIMEOUT
        proxy = UDSProxy(
            config.socket_path(backend),
            f"http://{backend.upstream_host}",
            timeout=timeout,
        )
        proxies[backend.name] = proxy
        for prefix in backend.prefixes:
            routes.append((prefix, proxy))
    routes.sort(key=lambda item: len(item[0]), reverse=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info(
            "intentframe-edge starting (run_dir=%s, backends=%s, tls=%s, mtls=%s, auth=%s)",
            config.run_dir,
            list(proxies),
            config.tls_enabled,
            config.mtls_enabled,
            bool(config.auth_token),
        )
        yield
        for proxy in proxies.values():
            await proxy.close()

    # Docs/OpenAPI are disabled: this is a network-facing ingress, not a
    # browsable API. Disabling them also avoids the duplicate-operation-id
    # warning the single catch-all route would otherwise emit.
    app = FastAPI(
        title="IntentFrame Edge",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def _check_auth(request: Request) -> None:
        if not config.auth_token:
            return
        provided = request.headers.get("authorization", "")
        expected = f"Bearer {config.auth_token}"
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _match(path: str) -> UDSProxy | None:
        for prefix, proxy in routes:
            if path == prefix or path.startswith(prefix + "/"):
                return proxy
        return None

    @app.get("/health")
    async def health() -> JSONResponse:
        backends = {name: await p.health() for name, p in proxies.items()}
        ok = all(backends.values())
        # 503 when any backend is down so container/k8s health probes
        # (which only inspect the status code) can detect a degraded edge.
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ok" if ok else "degraded", "backends": backends},
        )

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
    )
    async def proxy_route(full_path: str, request: Request) -> Response:
        _check_auth(request)
        path = request.url.path
        proxy = _match(path)
        if proxy is None:
            raise HTTPException(status_code=404, detail=f"No edge route for {path}")
        return await proxy.forward(request, path)

    return app


app = create_app()
