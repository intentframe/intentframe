"""
Local virtual filesystem implementation (POSIX).

Composes with the platform-agnostic MountPointResolver for path
arithmetic and provides actual file I/O operations using pathlib.

Agents see virtual paths (/invoices/, /documents/) -- never real
paths like /Users/john/Documents/. The mount point configuration
determines the mapping.
"""

from __future__ import annotations

import fnmatch
import logging
import mimetypes
from pathlib import Path

from executor_sdk.exceptions import VirtualFileSystemError
from executor_sdk.services.virtual_filesystem import (
    MountPointConfig,
    MountPointResolver,
    VirtualFileSystem,
)
from intentframe_native_kit.intentframe_native_bundles.shared.floors import check_vfs_write_floor

logger = logging.getLogger(__name__)


def _canonical_real_path(real_path: Path) -> str:
    """Canonical string form of *real_path* safe for prefix matching.

    Used for the deny-write floor check.  The path may not exist yet (the
    typical case for ``write_file``) so we canonicalize the parent and rejoin
    the filename — ``Path.resolve()`` on a missing file would fall back to
    string-level normalization on some Python versions.  Canonicalization
    is critical because floor prefixes like ``/tmp`` expand to
    ``/private/tmp`` on macOS; comparing non-canonical strings would miss
    symlink-based escapes.
    """
    try:
        return str(real_path.resolve(strict=False))
    except OSError:
        parent = real_path.parent.resolve(strict=False)
        return str(parent / real_path.name)


class LocalVirtualFileSystem(VirtualFileSystem):
    """Local filesystem VFS backed by MountPointResolver.

    Provides real file I/O through virtual path indirection.
    All path resolution delegates to MountPointResolver; this class
    only handles the actual read/write/list operations.
    """

    def __init__(
        self,
        mount_resolver: MountPointResolver | None = None,
        mounts: list[MountPointConfig] | None = None,
        base_path: Path | None = None,
        **_kwargs,
    ) -> None:
        """Initialize with a resolver or raw mount configs.

        Args:
            mount_resolver: Pre-built resolver (preferred).
            mounts: Raw mount configs (resolver built internally).
            base_path: Base path for resolving relative mounts.
        """
        if mount_resolver is not None:
            self._resolver = mount_resolver
        elif mounts is not None:
            self._resolver = MountPointResolver(mounts, base_path or Path.home())
        else:
            self._resolver = MountPointResolver([], Path.home())

    @property
    def resolver(self) -> MountPointResolver:
        """Access the underlying resolver (for advanced use)."""
        return self._resolver

    def list_directory(self, virtual_path: str) -> list[str]:
        """List entries in a virtual directory."""
        # Root listing -- show all mount points
        if virtual_path in ("/", ""):
            return self._resolver.list_root()

        mount, real_path = self._resolver.resolve(virtual_path)

        if not real_path.exists():
            return []

        if not real_path.is_dir():
            return []

        results: list[str] = []
        for item in real_path.iterdir():
            if item.is_dir():
                results.append(item.name + "/")
            elif item.is_file():
                # Apply file filter if configured
                if mount.file_filter:
                    if fnmatch.fnmatch(item.name, mount.file_filter):
                        results.append(item.name)
                else:
                    results.append(item.name)

        return sorted(results)

    _BINARY_UNSUPPORTED = frozenset({
        "image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff",
        "application/zip", "application/x-tar", "application/gzip",
        "application/octet-stream",
        "audio/mpeg", "video/mp4",
    })

    def read_file(self, virtual_path: str) -> str:
        """Read file contents as string.

        Supports plain text files and PDFs (via pymupdf text extraction).
        Returns a clear error for unsupported binary formats.
        """
        _mount, real_path = self._resolver.resolve(virtual_path)

        if not real_path.exists():
            raise VirtualFileSystemError(f"File not found: {virtual_path}")

        if not real_path.is_file():
            raise VirtualFileSystemError(f"Not a file: {virtual_path}")

        mime, _ = mimetypes.guess_type(str(real_path))

        if mime == "application/pdf":
            return self._read_pdf(real_path, virtual_path)

        if mime in self._BINARY_UNSUPPORTED:
            raise VirtualFileSystemError(
                f"Cannot read binary file ({mime}): {virtual_path}"
            )

        try:
            return real_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise VirtualFileSystemError(
                f"Cannot read binary file: {virtual_path}"
            )
        except Exception as exc:
            raise VirtualFileSystemError(
                f"Failed to read {virtual_path}: {exc}"
            ) from exc

    @staticmethod
    def _read_pdf(real_path: Path, virtual_path: str) -> str:
        try:
            import pymupdf
        except ImportError:
            raise VirtualFileSystemError(
                f"PDF support not available (pymupdf not installed): {virtual_path}"
            )

        try:
            doc = pymupdf.open(str(real_path))
            pages: list[str] = []
            for page in doc:
                text = page.get_text().strip()
                if text:
                    pages.append(text)
            doc.close()
        except Exception as exc:
            raise VirtualFileSystemError(
                f"Failed to extract text from PDF {virtual_path}: {exc}"
            ) from exc

        if not pages:
            return "(PDF contains no extractable text — may be scanned/image-only)"

        return "\n\n".join(pages)

    def write_file(self, virtual_path: str, content: str) -> bool:
        """Write content to a file.

        Enforces two gates in order:

        1. Mount writability — the VFS mount must be declared ``writable``.
        2. Non-negotiable deny-write floor — the resolved real path must not
           fall under :data:`intentframe_native_kit.resource_registry.floor.DENY_WRITE_PREFIXES`.
           This is symmetric with the Seatbelt ``NON_NEGOTIABLE_DENY_WRITE``
           list enforced for ``RUN_COMMAND`` in the macOS sandbox; without
           this check the VFS would let WRITE_FILE bypass the floor the
           sandbox otherwise guarantees.
        """
        mount, real_path = self._resolver.resolve(virtual_path)

        if not mount.writable:
            raise VirtualFileSystemError(
                f"Mount is read-only: {virtual_path}"
            )

        canonical = _canonical_real_path(real_path)
        matched = check_vfs_write_floor(canonical)
        if matched is not None:
            logger.warning(
                "WRITE_FILE blocked by deny-write floor: virtual=%r real=%r prefix=%r",
                virtual_path,
                canonical,
                matched,
            )
            raise VirtualFileSystemError(
                f"Write denied by non-negotiable floor ({matched}): {virtual_path}"
            )

        try:
            real_path.parent.mkdir(parents=True, exist_ok=True)
            real_path.write_text(content, encoding="utf-8")
            return True
        except Exception as exc:
            raise VirtualFileSystemError(
                f"Failed to write {virtual_path}: {exc}"
            ) from exc

    def delete_file(self, virtual_path: str) -> bool:
        """Delete a file under a writable mount, subject to the floor.

        Idempotent: returns ``True`` whether or not the file existed.  The
        floor check runs even when the target is absent so agents can't use
        DELETE_FILE to probe protected paths for existence based on the
        error string.
        """
        mount, real_path = self._resolver.resolve(virtual_path)

        if not mount.writable:
            raise VirtualFileSystemError(
                f"Mount is read-only: {virtual_path}"
            )

        canonical = _canonical_real_path(real_path)
        matched = check_vfs_write_floor(canonical)
        if matched is not None:
            logger.warning(
                "DELETE_FILE blocked by deny-write floor: virtual=%r real=%r prefix=%r",
                virtual_path,
                canonical,
                matched,
            )
            raise VirtualFileSystemError(
                f"Delete denied by non-negotiable floor ({matched}): {virtual_path}"
            )

        try:
            if real_path.exists():
                real_path.unlink()
            return True
        except Exception as exc:
            raise VirtualFileSystemError(
                f"Failed to delete {virtual_path}: {exc}"
            ) from exc

    def file_exists(self, virtual_path: str) -> bool:
        """Check if a virtual path points to an existing file."""
        try:
            _mount, real_path = self._resolver.resolve(virtual_path)
            return real_path.is_file()
        except VirtualFileSystemError:
            return False

    def is_writable(self, virtual_path: str) -> bool:
        """Check if a virtual path is within a writable mount."""
        return self._resolver.is_writable(virtual_path)
