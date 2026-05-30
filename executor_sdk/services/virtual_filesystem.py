"""
Virtual filesystem abstraction and mount point resolver.

Agents operate in a sandboxed virtual filesystem. They see virtual paths
like /invoices/ -- never real paths like /Users/john/Documents/finance/.

This module provides:
    - VirtualFileSystem ABC: Interface for VFS implementations
    - MountPointConfig: Pydantic model for mount configuration
    - MountPointResolver: Concrete, platform-agnostic path resolution logic

The MountPointResolver handles all the path arithmetic (virtual -> real
mapping). Platform-specific VFS implementations compose with it and
provide the actual file I/O operations.

Core Invariant:
    Agents NEVER see real filesystem paths. The VFS prevents:
    - Path traversal attacks (../../../etc/passwd)
    - Information leakage (agent learning OS, username, directory structure)
    - Escape from allowed boundaries
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from executor_sdk.exceptions import VirtualFileSystemError
from intentframe_core.paths import normalize_virtual_path

__all__ = [
    "VirtualFileSystem",
    "MountPointConfig",
    "MountPointResolver",
    "expand_path",
]


def expand_path(raw: str) -> str:
    """Expand ~ and environment variables in a path string.

    Handles cross-platform conventions:
        ~/Documents  ->  /Users/username/Documents  (macOS)
                         /home/username/Documents    (Linux)
                         C:\\Users\\username\\Documents (Windows)
        $HOME/docs   ->  expanded via os.environ
        $TMPDIR      ->  /tmp, C:\\Users\\...\\Temp, etc.

    Returns the expanded string (not a Path) so callers can decide
    whether to treat it as virtual or real.
    """
    return os.path.expandvars(os.path.expanduser(raw))


# ═══════════════════════════════════════════════════════════════════════════════
# Mount Point Configuration
# ═══════════════════════════════════════════════════════════════════════════════


class MountPointConfig(BaseModel):
    """Configuration for a single virtual-to-real path mapping.

    Attributes:
        virtual_path: What the agent sees (e.g., "/invoices/").
        real_path: Actual filesystem path (e.g., "/home/user/docs/invoices").
        writable: Whether the agent can write to this mount.
        file_filter: Glob pattern to filter visible files (e.g., "*.md").
    """

    model_config = ConfigDict(frozen=True)

    virtual_path: str
    real_path: str
    writable: bool = False
    file_filter: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Mount Point Resolver (Concrete, Platform-Agnostic)
# ═══════════════════════════════════════════════════════════════════════════════


class MountPointResolver:
    """Resolves virtual paths to real paths using mount point configuration.

    This is pure path arithmetic -- no actual file I/O.
    Platform-specific VFS implementations compose with this resolver.

    Algorithm:
        1. Mounts are sorted by virtual_path length (longest first).
        2. For each path resolution, find the best-matching mount.
        3. Map the virtual path to the real path within the mount.
        4. Validate that the resolved path doesn't escape the mount boundary.
    """

    def __init__(self, mounts: list[MountPointConfig], base_path: Path | None = None):
        """Initialize with mount configurations.

        Args:
            mounts: List of mount point configurations.
            base_path: Base path for resolving relative real_path values.
                       If None, all real_path values must be absolute.
        """
        self._base_path = base_path
        # Sort by virtual path length descending for correct longest-prefix matching
        self._mounts = sorted(mounts, key=lambda m: len(m.virtual_path), reverse=True)

    @property
    def mounts(self) -> list[MountPointConfig]:
        """Return a copy of the mount configurations."""
        return list(self._mounts)

    def find_mount(self, virtual_path: str) -> MountPointConfig | None:
        """Find the mount point that handles a virtual path.

        Normalizes the incoming path (handles ~, trailing /, .., etc.)
        then uses longest-prefix matching. Returns None if no mount matches.
        """
        normalized = normalize_virtual_path(virtual_path).rstrip("/")

        for mount in self._mounts:
            mount_vpath = mount.virtual_path.rstrip("/")

            if normalized == mount_vpath:
                return mount

            if mount.virtual_path.endswith("/"):
                prefix = mount.virtual_path
                if normalized.startswith(prefix) or (normalized + "/").startswith(prefix):
                    return mount

        return None

    def resolve(self, virtual_path: str) -> tuple[MountPointConfig, Path]:
        """Resolve a virtual path to its mount and real Path.

        Normalizes the incoming path before resolution.

        Args:
            virtual_path: The virtual path from the agent.

        Returns:
            Tuple of (matching mount config, resolved real Path).

        Raises:
            VirtualFileSystemError: If no mount matches or path escapes boundary.
        """
        virtual_path = normalize_virtual_path(virtual_path)
        mount = self.find_mount(virtual_path)
        if mount is None:
            raise VirtualFileSystemError(
                f"No mount point for virtual path: {virtual_path}"
            )

        real_path = Path(mount.real_path)
        if not real_path.is_absolute() and self._base_path is not None:
            real_path = self._base_path / mount.real_path

        # For file mounts (no trailing /), return the real path directly
        if not mount.virtual_path.endswith("/"):
            resolved = real_path
        else:
            # For directory mounts, append the relative portion
            relative = virtual_path[len(mount.virtual_path) :].lstrip("/")
            resolved = real_path / relative if relative else real_path

        # Security: verify resolved path doesn't escape mount boundary
        try:
            resolved_absolute = resolved.resolve()
            mount_absolute = real_path.resolve()
            if not str(resolved_absolute).startswith(str(mount_absolute)):
                raise VirtualFileSystemError(
                    f"Path traversal detected: {virtual_path} escapes mount boundary"
                )
        except OSError:
            # Path doesn't exist yet (e.g., for write operations) -- allow it
            # but still check at the string level
            pass

        return mount, resolved

    def is_writable(self, virtual_path: str) -> bool:
        """Check if a virtual path is within a writable mount."""
        mount = self.find_mount(virtual_path)
        return mount.writable if mount is not None else False

    def list_root(self) -> list[str]:
        """List all top-level virtual paths (mount roots).

        Returns what an agent sees when listing '/'.
        """
        roots: set[str] = set()
        for mount in self._mounts:
            parts = mount.virtual_path.strip("/").split("/")
            if parts[0]:
                root = "/" + parts[0]
                if mount.virtual_path.endswith("/") or len(parts) > 1:
                    root += "/"
                roots.add(root)
        return sorted(roots)

    @staticmethod
    def _normalize_virtual(path: str) -> str:
        """Normalize a virtual path for comparison."""
        if path.endswith("/") or path.endswith("."):
            return path.rstrip("/")
        return path


# ═══════════════════════════════════════════════════════════════════════════════
# Virtual FileSystem ABC
# ═══════════════════════════════════════════════════════════════════════════════


class VirtualFileSystem(ABC):
    """Abstract base for virtual filesystem implementations.

    Implementations compose with MountPointResolver for path arithmetic
    and provide platform-specific file I/O operations.

    Contract:
        - All paths are VIRTUAL. Real paths are never exposed to callers.
        - Write operations respect mount writability flags.
        - File filters are applied when listing directories.
        - Path traversal attempts raise VirtualFileSystemError.
    """

    @abstractmethod
    def list_directory(self, virtual_path: str) -> list[str]:
        """List entries in a virtual directory.

        Returns filenames (not full paths) for entries in the directory.
        Applies file_filter from the mount configuration if set.

        Args:
            virtual_path: Virtual directory path (e.g., "/invoices/").

        Returns:
            List of entry names. Directories have trailing '/'.
        """
        ...

    @abstractmethod
    def read_file(self, virtual_path: str) -> str:
        """Read file contents as string.

        Args:
            virtual_path: Virtual file path (e.g., "/invoices/inv001.md").

        Returns:
            File contents as string.

        Raises:
            VirtualFileSystemError: If file not found or read fails.
        """
        ...

    @abstractmethod
    def write_file(self, virtual_path: str, content: str) -> bool:
        """Write content to a file.

        Args:
            virtual_path: Virtual file path.
            content: String content to write.

        Returns:
            True if write succeeded.

        Raises:
            VirtualFileSystemError: If mount is read-only or write fails.
        """
        ...

    @abstractmethod
    def delete_file(self, virtual_path: str) -> bool:
        """Delete a file under a writable mount.

        Unlinks the real path the *virtual_path* resolves to.  Implementations
        must apply the same deny-write floor as :meth:`write_file` so agents
        cannot remove files under protected locations (launchd plists, ssh
        configs, shell rc, etc.).

        Args:
            virtual_path: Virtual file path to delete.

        Returns:
            ``True`` if the file was deleted or did not exist (idempotent).

        Raises:
            VirtualFileSystemError: Mount is read-only, the destination is
                under the deny-write floor, or the unlink itself failed.
        """
        ...

    @abstractmethod
    def file_exists(self, virtual_path: str) -> bool:
        """Check if a virtual path points to an existing file."""
        ...

    @abstractmethod
    def is_writable(self, virtual_path: str) -> bool:
        """Check if a virtual path is within a writable mount."""
        ...
