"""
Filesystem watch adapter -- file system event monitoring via watchdog.

Uses the watchdog library which automatically uses macOS FSEvents
for efficient native file monitoring.

Actions: WATCH_PATH, UNWATCH_PATH, LIST_WATCHES
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.models import AdapterManifest, ExecutionResult

logger = logging.getLogger(__name__)


class FilesystemWatchAdapter(CapabilityAdapter):
    """Filesystem event monitoring adapter using watchdog."""

    def __init__(self, **_kwargs) -> None:
        from watchdog.observers import Observer  # noqa: F401 -- validate dependency
        from watchdog.events import FileSystemEventHandler  # noqa: F401

        self._observer = None
        self._watches: dict[str, object] = {}

    def supported_actions(self) -> list[str]:
        return ["WATCH_PATH", "UNWATCH_PATH", "LIST_WATCHES"]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="filesystem_watch",
            name="Filesystem Watch Adapter",
            description="Monitor filesystem paths for changes (uses macOS FSEvents)",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        if action == "WATCH_PATH":
            return self._watch_path(params)
        if action == "UNWATCH_PATH":
            return self._unwatch_path(params)
        if action == "LIST_WATCHES":
            return self._list_watches()
        return ExecutionResult(success=False, error=f"Unknown action: {action}")

    def _watch_path(self, params: dict) -> ExecutionResult:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        path = params.get("path", "")
        recursive = params.get("recursive", True)

        if not path:
            return ExecutionResult(success=False, error="Path required")

        real_path = Path(path)
        if not real_path.exists():
            return ExecutionResult(success=False, error=f"Path not found: {path}")

        if path in self._watches:
            return ExecutionResult(success=True, data={"path": path, "already_watching": True})

        # Ensure observer is running
        if self._observer is None:
            self._observer = Observer()
            self._observer.start()

        class LoggingHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                logger.info(
                    "FS event: type=%s path=%s", event.event_type, event.src_path
                )

        handler = LoggingHandler()
        watch = self._observer.schedule(handler, str(real_path), recursive=recursive)
        self._watches[path] = watch

        return ExecutionResult(
            success=True,
            data={"path": path, "watching": True, "recursive": recursive},
        )

    def _unwatch_path(self, params: dict) -> ExecutionResult:
        path = params.get("path", "")

        if path not in self._watches:
            return ExecutionResult(success=False, error=f"Not watching: {path}")

        if self._observer:
            self._observer.unschedule(self._watches[path])

        del self._watches[path]

        # Stop observer if no more watches
        if not self._watches and self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        return ExecutionResult(success=True, data={"path": path, "unwatched": True})

    def _list_watches(self) -> ExecutionResult:
        return ExecutionResult(
            success=True,
            data={"watches": list(self._watches.keys()), "count": len(self._watches)},
        )

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(success=False, error="Filesystem watch is not rollbackable")
