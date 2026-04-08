"""
Cross-platform virtual path normalization.

Shared by the Guardian (constraint checking) and VFS (mount resolution)
so that LLM-generated paths like "/home", "/home/", "~/Documents", and
"home/Documents" all resolve to the same canonical form.

The virtual home root is /home/ — this is what agents see regardless of
the real OS path (/Users/username/, /home/username/, C:\\Users\\username\\).

Security canonicalization pipeline (runs before any path logic):
    1. URL-decode repeatedly      — defeats %2e%2e, %252e%252e, etc.
    2. Unicode NFKC normalization — folds fullwidth ．／ to ASCII ./
    3. Strip control characters   — removes null bytes, \r, \x1b, etc.
    4. Backslash → forward slash  — prevents \\..\\ traversal on Windows
    5. posixpath.normpath          — resolves .. and . canonically
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
from urllib.parse import unquote

__all__ = ["normalize_virtual_path", "VIRTUAL_HOME"]

VIRTUAL_HOME = "/home"

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _canonicalize(path: str) -> str:
    """Security-first canonicalization of an untrusted virtual path string.

    Applied before any path semantics so that encoding tricks, Unicode
    confusables, and control-character injections are neutralised.
    """
    prev = path
    while True:
        decoded = unquote(prev)
        if decoded == prev:
            break
        prev = decoded
    path = prev

    path = unicodedata.normalize("NFKC", path)

    path = _CONTROL_CHARS_RE.sub("", path)

    path = path.replace("\\", "/")

    return path


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
    path = _canonicalize(raw.strip())

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
