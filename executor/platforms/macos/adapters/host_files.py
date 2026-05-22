"""Host files adapter -- real-path file operations (no VFS).

Parallel to :class:`FilesAdapter` but operates directly on real host
paths with no ``MountPointResolver`` indirection.  Agents speak the
host's own vocabulary (``~/Documents/foo.txt``) rather than the virtual
mount vocabulary (``/home/foo.txt``).

Actions: READ_HOST_FILE, WRITE_HOST_FILE, DELETE_HOST_FILE,
LIST_HOST_DIRECTORY.

Enforcement walls (run in order before any I/O):

1. ``resource_registry.floor.match_deny_prefix`` — non-negotiable
   deny-write floor.  Rejects writes/deletes into launchd plists, shell
   rc files, ``~/.ssh``, ``/etc/sudoers``, etc.  Peer of the floor check
   inside :class:`LocalVirtualFileSystem`.
2. :class:`HostFilesConfig` ``allowed_read_paths`` / ``allowed_write_paths`` —
   the executor YAML ceiling.  Reads must land under
   ``allowed_read_paths``, writes/deletes under ``allowed_write_paths``.

This adapter does **not** consult the user policy's
``HostFileConstraints`` — that check belongs to the guardian's
:class:`HostFileChecker`, which runs earlier in the pipeline.  The
adapter is a second, independent wall so a compromised guardian path
still cannot escape the executor-level ceiling.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from pathlib import Path

from action_registry import ActionType
from executor.adapters.base import CapabilityAdapter
from executor.config.schema import HostFilesConfig
from executor.models import AdapterManifest, ExecutionResult
from resource_registry.floor import canonicalize_real_path

# MIME types we refuse up-front rather than surfacing cryptic decode
# errors.  Mirrors LocalVirtualFileSystem._BINARY_UNSUPPORTED so the
# two file-reading surfaces agree on what "binary" means; kept in
# lockstep intentionally — adding a type here without the peer leaves
# one family able to read what the other rejects.
_BINARY_UNSUPPORTED = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff",
    "application/zip", "application/x-tar", "application/gzip",
    "application/octet-stream",
    "audio/mpeg", "video/mp4",
})


def _read_pdf_text(real_path: Path) -> str:
    """Extract text from a PDF via pymupdf.

    Returns the concatenated page text (pages joined by a blank line)
    or a human-readable placeholder when the PDF has no extractable
    text layer (scanned/image-only PDFs).  Raises ``RuntimeError`` on
    missing optional dep or extraction failure — callers convert into
    their native error surface.
    """
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PDF support not available (pymupdf not installed)"
        ) from exc

    pages: list[str] = []
    try:
        doc = pymupdf.open(str(real_path))
    except Exception as exc:
        raise RuntimeError(f"failed to extract PDF text: {exc}") from exc
    try:
        for page in doc:
            text = page.get_text().strip()
            if text:
                pages.append(text)
    except Exception as exc:
        raise RuntimeError(f"failed to extract PDF text: {exc}") from exc
    finally:
        doc.close()

    if not pages:
        return "(PDF contains no extractable text — may be scanned/image-only)"
    return "\n\n".join(pages)


class HostFilesAdapter(CapabilityAdapter):
    """Real-path file operations bypassing the virtual filesystem."""

    def __init__(
        self,
        host_files_cfg: HostFilesConfig,
        **_kwargs,
    ) -> None:
        self._cfg = host_files_cfg

    def supported_actions(self) -> list[str]:
        return [
            ActionType.READ_HOST_FILE.value,
            ActionType.WRITE_HOST_FILE.value,
            ActionType.DELETE_HOST_FILE.value,
            ActionType.LIST_HOST_DIRECTORY.value,
        ]

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="host_files",
            name="Host Files Adapter",
            description=(
                "Real-path file operations (read, write, delete, list) "
                "bypassing the virtual filesystem."
            ),
            supported_actions=self.supported_actions(),
            requires_credentials=False,
        )

    async def execute(
        self,
        action: str,
        params: dict,
        credentials: dict | None = None,
    ) -> ExecutionResult:
        # Run file I/O in a worker thread so the async event loop stays
        # responsive during blocking disk calls.
        return await asyncio.to_thread(self._execute_sync, action, params)

    def _execute_sync(self, action: str, params: dict) -> ExecutionResult:
        raw_path = params.get("path", "")
        if not raw_path:
            return ExecutionResult(
                success=False, error="host_files: missing 'path' parameter"
            )

        canonical = canonicalize_real_path(raw_path)

        # Wall 1: non-negotiable floor for any mutating op.
        if action in {
            ActionType.WRITE_HOST_FILE.value,
            ActionType.DELETE_HOST_FILE.value,
        }:
            from intentframe_action_bundle.executor.floors import check_host_file_floor

            matched = check_host_file_floor(canonical, action)
            if matched is not None:
                return ExecutionResult(
                    success=False,
                    error=(
                        f"host_files: non-negotiable floor refused "
                        f"{action.lower()} under {matched!r}"
                    ),
                )

        # Wall 2: executor YAML ceiling.
        scope = (
            self._cfg.allowed_read_paths
            if action in {
                ActionType.READ_HOST_FILE.value,
                ActionType.LIST_HOST_DIRECTORY.value,
            }
            else self._cfg.allowed_write_paths
        )
        if not self._within_scope(canonical, scope):
            return ExecutionResult(
                success=False,
                error=(
                    f"host_files: path {raw_path!r} not within executor "
                    f"{action.lower()} allowlist"
                ),
            )

        if action == ActionType.READ_HOST_FILE.value:
            return self._read(canonical, params)
        if action == ActionType.LIST_HOST_DIRECTORY.value:
            return self._list(canonical)
        if action == ActionType.WRITE_HOST_FILE.value:
            return self._write(canonical, params)
        if action == ActionType.DELETE_HOST_FILE.value:
            return self._delete(canonical)

        return ExecutionResult(
            success=False, error=f"Unknown host file action: {action}"
        )

    @staticmethod
    def _within_scope(canonical: str, scope: list[str]) -> bool:
        """Return True iff *canonical* is equal to or nested under any scope entry.

        ``HostFilesConfig`` canonicalizes the entries once at load time,
        so this is a pure string prefix comparison with a separator
        boundary — the ``os.sep`` check prevents ``/Users/me-evil``
        from matching ``/Users/me``.
        """
        if not scope:
            return False
        for allowed in scope:
            if canonical == allowed:
                return True
            if canonical.startswith(allowed.rstrip(os.sep) + os.sep):
                return True
        return False

    def _read(self, canonical: str, params: dict) -> ExecutionResult:
        p = Path(canonical)
        if not p.exists():
            return ExecutionResult(
                success=False, error=f"host_files: file not found: {canonical}"
            )
        if p.is_dir():
            return ExecutionResult(
                success=False,
                error=f"host_files: path is a directory, use LIST_HOST_DIRECTORY: {canonical}",
            )

        # MIME-driven decoding matches LocalVirtualFileSystem.read_file:
        # PDFs go through pymupdf text extraction, known binary types
        # are refused with a clear reason, and plain text is decoded as
        # UTF-8 so a stray latin-1 byte doesn't surface as the default
        # locale-decoder's cryptic traceback.
        mime, _ = mimetypes.guess_type(canonical)

        if mime == "application/pdf":
            try:
                content = _read_pdf_text(p)
            except RuntimeError as exc:
                return ExecutionResult(
                    success=False, error=f"host_files: {exc}: {canonical}"
                )
        elif mime in _BINARY_UNSUPPORTED:
            return ExecutionResult(
                success=False,
                error=f"host_files: cannot read binary file ({mime}): {canonical}",
            )
        else:
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return ExecutionResult(
                    success=False,
                    error=f"host_files: cannot read binary file: {canonical}",
                )
            except Exception as exc:
                return ExecutionResult(
                    success=False,
                    error=f"host_files: failed to read {canonical}: {exc}",
                )

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
                "path": canonical,
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
                "truncated": truncated,
            },
        )

    def _list(self, canonical: str) -> ExecutionResult:
        p = Path(canonical)
        if not p.exists():
            return ExecutionResult(
                success=False, error=f"host_files: directory not found: {canonical}"
            )
        if not p.is_dir():
            return ExecutionResult(
                success=False,
                error=f"host_files: not a directory: {canonical}",
            )
        entries: list[dict] = []
        for child in sorted(p.iterdir()):
            entries.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "is_file": child.is_file(),
                }
            )
        return ExecutionResult(
            success=True, data={"entries": entries, "path": canonical}
        )

    def _write(self, canonical: str, params: dict) -> ExecutionResult:
        content = params.get("content", "")
        if not isinstance(content, str):
            return ExecutionResult(
                success=False,
                error="host_files: 'content' parameter must be a string",
            )
        p = Path(canonical)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Explicit UTF-8 matches LocalVirtualFileSystem.write_file and
        # makes the round-trip with _read's utf-8 decode deterministic
        # across locales (the platform default on macOS is utf-8 but
        # pinning it here prevents surprises if that ever changes).
        p.write_text(content, encoding="utf-8")
        return ExecutionResult(
            success=True,
            data={"path": canonical, "bytes_written": len(content)},
            rollback_available=True,
            rollback_id=f"host_file_write:{canonical}",
        )

    def _delete(self, canonical: str) -> ExecutionResult:
        p = Path(canonical)
        if not p.exists():
            # Idempotent delete — matches FilesAdapter / VFS semantics.
            return ExecutionResult(
                success=True, data={"path": canonical, "deleted": False}
            )
        if p.is_dir():
            return ExecutionResult(
                success=False,
                error=(
                    f"host_files: refusing to delete directory "
                    f"(unsupported): {canonical}"
                ),
            )
        p.unlink()
        return ExecutionResult(
            success=True, data={"path": canonical, "deleted": True}
        )

    async def rollback(self, rollback_id: str) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            error="Host file rollback requires state store checkpoint (not yet implemented)",
        )
