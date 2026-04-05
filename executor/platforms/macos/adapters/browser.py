"""
Browser adapter -- macOS default browser via `open` + httpx for content fetching.

OPEN_URL and SEARCH_WEB are intentionally GUI-visible actions (the user's
default browser opens as expected). GET_PAGE_CONTENT fetches pages headlessly
via httpx without opening any browser.

PyXA dependency removed: `open` subprocess replaces PyXA.Application("Safari").

Actions: OPEN_URL, GET_PAGE_CONTENT, SEARCH_WEB
"""

from __future__ import annotations

import asyncio
import subprocess
import urllib.parse

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult


class BrowserAdapter(CapabilityAdapter):
    """macOS browser adapter: default browser via `open`, content fetch via httpx."""

    def __init__(self, **_kwargs) -> None:
        pass  # no external deps required

    def supported_actions(self) -> list[str]:
        return [
            ActionType.OPEN_URL.value,
            ActionType.GET_PAGE_CONTENT.value,
            ActionType.SEARCH_WEB.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="browser",
            name="Browser Adapter",
            description="macOS browser: open URLs in default browser, fetch page content",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        if action == "OPEN_URL":
            return await asyncio.to_thread(self._open_url, params)
        if action == "GET_PAGE_CONTENT":
            return await self._get_page_content(params)
        if action == "SEARCH_WEB":
            return await asyncio.to_thread(self._search_web, params)
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    @staticmethod
    def _open_url(params: dict) -> ExecutionResult:
        url = params.get("url", "")
        if not url:
            return ExecutionResult(success=False, error="URL required")

        try:
            subprocess.run(["open", url], check=True, capture_output=True, timeout=10)
        except subprocess.CalledProcessError as exc:
            return ExecutionResult(success=False, error=f"Failed to open URL: {exc}")
        except Exception as exc:
            return ExecutionResult(success=False, error=f"Failed to open URL: {exc}")

        return ExecutionResult(success=True, data={"url": url, "opened": True})

    @staticmethod
    async def _get_page_content(params: dict) -> ExecutionResult:
        import trafilatura  # noqa: PLC0415

        url = params.get("url", "")
        if not url:
            return ExecutionResult(success=False, error="URL required")

        try:
            downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
            if not downloaded:
                return ExecutionResult(success=False, error=f"Failed to fetch URL: {url}")

            content = trafilatura.extract(
                downloaded,
                output_format="markdown",
                include_links=True,
                include_tables=True,
            ) or downloaded[:10_000]

            return ExecutionResult(
                success=True,
                data={
                    "url": url,
                    "content": content,
                },
            )
        except Exception as exc:
            return ExecutionResult(success=False, error=f"Failed to fetch: {exc}")

    @staticmethod
    def _search_web(params: dict) -> ExecutionResult:
        query = params.get("query", "")
        if not query:
            return ExecutionResult(success=False, error="Search query required")

        search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"

        try:
            subprocess.run(["open", search_url], check=True, capture_output=True, timeout=10)
        except Exception as exc:
            return ExecutionResult(success=False, error=f"Failed to open search: {exc}")

        return ExecutionResult(
            success=True,
            data={"query": query, "url": search_url, "opened": True},
        )

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Browser actions are irreversible")
