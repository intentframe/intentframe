"""
Spotlight adapter -- macOS Spotlight search via mdfind CLI.

Actions: SEARCH_SPOTLIGHT
"""

from __future__ import annotations

import asyncio
import subprocess

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.models import AdapterManifest, ExecutionResult


class SpotlightAdapter(CapabilityAdapter):
    """macOS Spotlight search adapter via mdfind."""

    def __init__(self, **_kwargs) -> None:
        pass

    def supported_actions(self) -> list[str]:
        return [ActionType.SEARCH_SPOTLIGHT.value]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="spotlight",
            name="Spotlight Adapter",
            description="macOS Spotlight: search files and content",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        if action != "SEARCH_SPOTLIGHT":
            return ExecutionResult(success=False, error=f"Unknown action: {action}")

        return await asyncio.to_thread(self._search, params)

    @staticmethod
    def _search(params: dict) -> ExecutionResult:
        query = params.get("query", "")
        scope = params.get("scope")  # Optional directory to search in
        limit = params.get("limit", 20)
        kind = params.get("kind")  # Optional: document, image, etc.

        if not query:
            return ExecutionResult(success=False, error="Search query required")

        cmd = ["mdfind"]

        if scope:
            cmd.extend(["-onlyin", scope])

        # Build the query with optional kind filter
        if kind:
            mdfind_query = f'(kMDItemDisplayName == "*{query}*"cd) && (kMDItemKind == "*{kind}*"cd)'
        else:
            mdfind_query = query

        cmd.append(mdfind_query)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15
            )
            paths = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
            paths = paths[:limit]

            return ExecutionResult(
                success=True,
                data={
                    "results": paths,
                    "count": len(paths),
                    "query": query,
                },
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(success=False, error="Spotlight search timed out")

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Search is a read-only operation")
