"""
Files adapter -- VFS-backed file operations.

Agents interact with a virtual filesystem. They see virtual paths
(/invoices/, /documents/) and never learn real filesystem paths.
All path resolution goes through the MountPointResolver.

Actions: LIST_DIRECTORY, READ_FILE, WRITE_FILE, APPEND_ROW, DELETE_FILE
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.exceptions import VirtualFileSystemError
from executor.models import AdapterManifest, ExecutionResult
from executor.platforms.macos.virtual_filesystem import LocalVirtualFileSystem
from executor.services.virtual_filesystem import MountPointResolver


class FilesAdapter(CapabilityAdapter):
    """File operations through the virtual filesystem."""

    def __init__(
        self,
        mount_resolver: MountPointResolver | None = None,
        base_path: Path | None = None,
        **_kwargs,
    ) -> None:
        self._vfs = LocalVirtualFileSystem(
            mount_resolver=mount_resolver,
            base_path=base_path,
        )

    def supported_actions(self) -> list[str]:
        return [
            ActionType.LIST_DIRECTORY.value,
            ActionType.READ_FILE.value,
            ActionType.WRITE_FILE.value,
            ActionType.APPEND_ROW.value,
            ActionType.DELETE_FILE.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="files",
            name="Files Adapter",
            description="Virtual filesystem operations (list, read, write, append, delete)",
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(self, action: str, params: dict, credentials: dict | None = None) -> ExecutionResult:
        # Run file I/O in thread to not block event loop
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        path = params.get("path", "")

        try:
            if action == "LIST_DIRECTORY":
                entries = self._vfs.list_directory(path)
                return ExecutionResult(success=True, data={"entries": entries, "path": path})

            if action == "READ_FILE":
                content = self._vfs.read_file(path)
                lines = content.splitlines(keepends=True)
                total_lines = len(lines)

                offset = params.get("offset", 0)
                limit = params.get("limit", 500)
                sliced = lines[offset : offset + limit]
                truncated = (offset + limit) < total_lines

                return ExecutionResult(
                    success=True,
                    data={
                        "content": "".join(sliced),
                        "path": path,
                        "total_lines": total_lines,
                        "offset": offset,
                        "limit": limit,
                        "truncated": truncated,
                    },
                )

            if action == "WRITE_FILE":
                content = params.get("content", "")
                self._vfs.write_file(path, content)
                return ExecutionResult(
                    success=True,
                    data={"path": path, "bytes_written": len(content)},
                    rollback_available=True,
                    rollback_id=f"file_write:{path}",
                )

            if action == "APPEND_ROW":
                row = {k: v for k, v in params.items() if k != "path"}
                values = [str(v) for v in row.values()]
                row_text = "| " + " | ".join(values) + " |\n"
                existing = self._vfs.read_file(path) if self._vfs.file_exists(path) else ""
                self._vfs.write_file(path, existing + row_text)
                return ExecutionResult(success=True, data={"path": path, "row": row})

            if action == "DELETE_FILE":
                # Delegated to the VFS so the deny-write floor applies symmetrically
                # with WRITE_FILE (see executor/platforms/macos/virtual_filesystem.py
                # and resource_registry/floor.py).  Previously this adapter reached
                # into the resolver directly and bypassed the floor entirely.
                self._vfs.delete_file(path)
                return ExecutionResult(success=True, data={"path": path, "deleted": True})

            return ExecutionResult(success=False, error=f"Unknown file action: {action}")

        except VirtualFileSystemError as exc:
            return ExecutionResult(success=False, error=str(exc))

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        # File rollback would require stored checkpoints
        return ExecutionResult(
            success=False,
            error="File rollback requires state store checkpoint (not yet implemented)",
        )
