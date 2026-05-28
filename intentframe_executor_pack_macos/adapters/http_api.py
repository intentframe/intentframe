"""
HTTP API adapter -- REST API calls via httpx.

Provides async HTTP client capabilities for making external API
calls. Supports GET, POST, PUT, DELETE with headers, query params,
and JSON body.

Actions: HTTP_GET, HTTP_POST, HTTP_PUT, HTTP_DELETE
"""

from __future__ import annotations

import logging

import httpx

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)

DEFAULT_HTTP_TIMEOUT = 30.0
MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB


class HttpApiAdapter(CapabilityAdapter):
    """HTTP REST API adapter using httpx."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [
            ActionType.HTTP_GET.value,
            ActionType.HTTP_POST.value,
            "HTTP_PUT",
            "HTTP_DELETE",
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="http_api",
            name="HTTP API Adapter",
            description="Make REST API calls (GET, POST, PUT, DELETE)",
            supported_actions=self.supported_actions(),
            requires_credentials=True,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        url = params.get("url", "")
        if not url:
            return ExecutionResult(success=False, error="No URL provided")

        headers = params.get("headers", {})
        query_params = params.get("query_params", {})
        body = params.get("body")
        timeout = params.get("timeout", DEFAULT_HTTP_TIMEOUT)

        # Inject auth credentials into headers if provided
        if credentials:
            api_key = credentials.get("api_key")
            if api_key:
                headers.setdefault("Authorization", f"Bearer {api_key}")

        method_map = {
            "HTTP_GET": "GET",
            "HTTP_POST": "POST",
            "HTTP_PUT": "PUT",
            "HTTP_DELETE": "DELETE",
        }
        method = method_map.get(action)
        if method is None:
            return ExecutionResult(success=False, error=f"Unknown action: {action}")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=query_params,
                    json=body if body and method in ("POST", "PUT") else None,
                )

                # Truncate response if too large
                response_text = response.text[:MAX_RESPONSE_SIZE]

                # Try to parse as JSON
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response_text

                success = 200 <= response.status_code < 400

                return ExecutionResult(
                    success=success,
                    data={
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": response_data,
                        "url": str(response.url),
                    },
                    error=f"HTTP {response.status_code}" if not success else None,
                )

        except httpx.TimeoutException:
            return ExecutionResult(success=False, error=f"HTTP request timed out: {url}")
        except httpx.ConnectError as exc:
            return ExecutionResult(success=False, error=f"Connection failed: {exc}")

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            error="HTTP requests are irreversible",
        )
