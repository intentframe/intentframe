"""
Files adapter -- VFS-backed file operations.

Agents interact with a virtual filesystem. They see virtual paths
(/invoices/, /documents/) and never learn real filesystem paths.
All path resolution goes through the MountPointResolver.

Actions: LIST_DIRECTORY, READ_FILE, WRITE_FILE, APPEND_ROW, DELETE_FILE
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from action_registry import ActionType
from executor_sdk.adapters.base import CapabilityAdapter
from executor_sdk.exceptions import VirtualFileSystemError
from executor_sdk.models import AdapterManifest, ExecutionResult
from executor_sdk.services.virtual_filesystem import MountPointConfig, expand_path
from ..virtual_filesystem import LocalVirtualFileSystem
from .files_config import FilesConfig, FilesMount

logger = logging.getLogger(__name__)


def _mounts_from_config(entries: list[FilesMount]) -> list[MountPointConfig]:
    return [
        MountPointConfig(
            virtual_path=m.virtual_path,
            real_path=expand_path(m.real_path),
            writable=m.writable,
            file_filter=m.file_filter,
        )
        for m in entries
    ]


class FilesAdapter(CapabilityAdapter):
    """File operations through the virtual filesystem."""

    def __init__(
        self,
        pack_options: dict[str, dict[str, Any]] | None = None,
        files_options: dict[str, Any] | FilesConfig | None = None,
        **_kwargs,
    ) -> None:
        raw = files_options
        if raw is None and pack_options is not None:
            raw = pack_options.get("files")

        cfg = raw if isinstance(raw, FilesConfig) else FilesConfig.model_validate(raw or {})

        default_base = Path(expand_path(cfg.base_path)) if cfg.base_path else Path.home()
        mounts, base_path = self._resolve_mounts(cfg, default_base)
        self._vfs = LocalVirtualFileSystem(mounts=mounts, base_path=base_path)

    @staticmethod
    def _resolve_mounts(
        cfg: FilesConfig, default_base: Path
    ) -> tuple[list[MountPointConfig], Path]:
        """Build mount list from registry (if workspace_id set) or static config."""
        if cfg.workspace_id:
            try:
                from resource_registry.client import ResourceRegistryClient

                rr = ResourceRegistryClient()
                view = rr.executor_view(cfg.workspace_id)
                rr.close()
                eff_base = view.base_path or default_base
                mounts = [
                    MountPointConfig(
                        virtual_path=m.virtual_path,
                        real_path=expand_path(m.real_path),
                        writable=m.writable,
                        file_filter=m.file_filter,
                    )
                    for m in view.mounts
                ]
                logger.info(
                    "VFS mounts from resource registry: workspace=%s, %d mounts",
                    cfg.workspace_id,
                    len(mounts),
                )
                return mounts, eff_base
            except Exception as exc:
                logger.debug(
                    "Resource registry unavailable for workspace=%r (%s), "
                    "falling back to static mounts",
                    cfg.workspace_id,
                    exc,
                )

        return _mounts_from_config(cfg.mounts), default_base

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
                # with WRITE_FILE (see virtual_filesystem.py and
                # resource_registry/floor.py).  The adapter never reaches into the
                # resolver directly, which would bypass the floor entirely.
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
