"""Safe, opt-in resolution of referenced script paths to file contents.

`command_shield` stays stateless by default; this module is only used
when :class:`ShieldConfig.auto_resolve_local` is True AND the caller
supplies a :class:`ResolveSession`.  The session carries the
resolution base (`cwd`) and optional policy knobs (`allow_roots`,
`follow_symlinks`) — never inferred from the running process's state.

Guarantees:

* Never executes anything.
* Never follows symlinks unless explicitly opted in.
* Never reads more than ``max_bytes`` — oversized files return ``None``
  with ``reason="too-large"``.
* Never raises.  On any OS error returns ``None`` with a diagnostic
  reason the pipeline turns into a ``resolved:*`` signal.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field

from command_shield.verdict import Edge


@dataclass(frozen=True)
class ResolveSession:
    """Caller-supplied resolution context — never inferred by the module.

    Attributes:
        cwd: Base directory used to resolve relative paths.  Typically
            the session's working directory, not ``os.getcwd()``.
        allow_roots: Optional tuple of absolute directory prefixes.
            When non-empty, resolved paths must start with one of
            these or resolution fails with reason ``"outside-allow-roots"``.
        follow_symlinks: When False (default), any symlink in the
            resolved path causes resolution to fail with reason
            ``"symlink"``.
    """

    cwd: str
    allow_roots: tuple[str, ...] = ()
    follow_symlinks: bool = False


@dataclass(frozen=True)
class ResolvedScript:
    """Result of :func:`resolve_script` on a referenced edge."""

    path: str
    content: bytes            # raw bytes; caller decides decoding
    truncated: bool = False   # True when file was larger than max_bytes
    reason: str = "ok"


@dataclass(frozen=True)
class ResolveFailure:
    """Why resolution failed.  Pipeline maps `reason` to `resolved:*` signal."""

    reason: str
    detail: str = ""


def _is_safe_path(path: str) -> bool:
    """Reject paths containing null bytes or which are empty."""
    return bool(path) and "\x00" not in path


def _normalize(session: ResolveSession, path_arg: str) -> str:
    """Join path_arg onto session.cwd and normalise.  No realpath."""
    if os.path.isabs(path_arg):
        base = path_arg
    else:
        base = os.path.join(session.cwd, path_arg)
    return os.path.normpath(base)


def _within_allow_roots(path: str, roots: tuple[str, ...]) -> bool:
    if not roots:
        return True
    abspath = os.path.abspath(path)
    for root in roots:
        root_abs = os.path.abspath(root).rstrip(os.sep)
        if abspath == root_abs or abspath.startswith(root_abs + os.sep):
            return True
    return False


def resolve_script(
    edge: Edge,
    session: ResolveSession | None,
    *,
    max_bytes: int = 1_000_000,
) -> ResolvedScript | ResolveFailure:
    """Read the file referenced by *edge* under *session*'s policy.

    Preconditions:
        edge.kind == "referenced" and edge.resolvable is True

    Returns :class:`ResolvedScript` on success or :class:`ResolveFailure`
    with a `reason` string the pipeline translates into a signal.
    """
    if session is None:
        return ResolveFailure(reason="no-session")

    if edge.kind != "referenced" or not edge.resolvable or not edge.path_arg:
        return ResolveFailure(reason="not-resolvable")

    if not _is_safe_path(edge.path_arg):
        return ResolveFailure(reason="unsafe-path", detail=edge.path_arg[:120])

    path = _normalize(session, edge.path_arg)

    if not _within_allow_roots(path, session.allow_roots):
        return ResolveFailure(reason="outside-allow-roots", detail=path[:200])

    try:
        st = os.lstat(path)
    except (OSError, ValueError) as exc:
        return ResolveFailure(reason="stat-failed", detail=f"{exc}"[:120])

    if stat.S_ISLNK(st.st_mode):
        if not session.follow_symlinks:
            return ResolveFailure(reason="symlink", detail=path[:200])
        try:
            st = os.stat(path)
        except (OSError, ValueError) as exc:
            return ResolveFailure(reason="stat-failed", detail=f"{exc}"[:120])

    if not stat.S_ISREG(st.st_mode):
        return ResolveFailure(reason="not-regular-file", detail=path[:200])

    size = st.st_size
    truncated = False
    if size > max_bytes:
        truncated = True

    try:
        with open(path, "rb") as fh:
            data = fh.read(max_bytes + 1) if truncated else fh.read(max_bytes)
    except (OSError, ValueError) as exc:
        return ResolveFailure(reason="read-failed", detail=f"{exc}"[:120])

    if truncated:
        # Drop the sentinel extra byte so caller sees exactly max_bytes
        # with an honest truncated flag.
        data = data[:max_bytes]

    return ResolvedScript(
        path=path,
        content=data,
        truncated=truncated,
        reason="ok",
    )


__all__ = ["ResolveSession", "ResolvedScript", "ResolveFailure", "resolve_script"]
