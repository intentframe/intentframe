"""
Cross-platform virtual path normalization.

Shared by the Guardian (constraint checking) and VFS (mount resolution)
so that LLM-generated paths like "/home", "/home/", "~/Documents", and
"home/Documents" all resolve to the same canonical form.

The virtual home root is /home/ — this is what agents see regardless of
the real OS path (/Users/username/, /home/username/, C:\\Users\\username\\).
"""

from __future__ import annotations

import posixpath

__all__ = ["normalize_virtual_path", "VIRTUAL_HOME"]

VIRTUAL_HOME = "/home"


def normalize_virtual_path(raw: str) -> str:
    """Normalize a virtual path the way a shell would.

    Handles:
        ~               →  /home/
        ~/Documents     →  /home/Documents/
        /home           →  /home/
        /home/          →  /home/
        /home//foo      →  /home/foo
        /home/./foo     →  /home/foo
        home/foo        →  /home/foo
        /home/bar/../x  →  /home/x
        (empty)         →  /

    Directories (no file extension in last component) get a trailing /.
    Files keep no trailing /.
    """
    path = raw.strip()

    if not path or path == "/":
        return "/"

    if path == "~" or path == "~/":
        return VIRTUAL_HOME + "/"

    if path.startswith("~/"):
        path = VIRTUAL_HOME + "/" + path[2:]

    if not path.startswith("/"):
        path = "/" + path

    path = posixpath.normpath(path)

    if _looks_like_directory(raw, path):
        path = path.rstrip("/") + "/"

    return path


def _looks_like_directory(raw: str, normalized: str) -> bool:
    """Heuristic: treat as directory if the original had trailing / or
    the final component has no file extension."""
    if raw.rstrip().endswith("/"):
        return True
    basename = posixpath.basename(normalized)
    if not basename:
        return True
    return "." not in basename
