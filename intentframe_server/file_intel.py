"""
Build deterministic ``FileIntel`` facts for WRITE_FILE-family actions.

This module assembles a ``FileIntel`` object from:

  - payload inspection via ``command_shield.inspect_code()``
  - destination probing via ``stat`` / ``lstat`` / ``readlink``
  - path classification via ``classify_path_category()``
  - floor-prefix matching via ``match_deny_prefix()``

Public helpers:

  ``build_file_intel(content, target, action_value)``
    Return a complete ``FileIntel`` for a WRITE_FILE or WRITE_HOST_FILE
    action.  Failures degrade to defaults rather than propagating.

  ``build_destination_intel(action_value, target)``
    Return the destination-side fields as a dict suitable for splatting
    into ``FileIntel(...)``.

  ``extension_of(target)``
    Return ``Path(target).suffix.lower()`` or ``None`` when the target
    has no suffix.
"""

from __future__ import annotations

import logging
import os
import stat as _stat_mod
from pathlib import Path

from action_registry.types import ActionType
from command_shield import inspect_code as shield_inspect_code
from intentframe_components.heuristics import classify_path_category
from intentframe_core.types import (
    FILE_DESTINATION_KIND,
    FILE_PARENT_KIND,
    FileIntel,
)
from resource_registry.floor import canonicalize_real_path, match_deny_prefix

logger = logging.getLogger(__name__)

__all__ = [
    "build_file_intel",
    "build_destination_intel",
    "extension_of",
]


# ─────────────────────────────────────────────────────────────────────
# Path-derived helpers
# ─────────────────────────────────────────────────────────────────────


def extension_of(target: str | None) -> str | None:
    """Normalized lowercase extension (``".py"``) or ``None`` if absent.

    Pure string operation on the target.  Empty / None targets return
    ``None``; targets without a suffix return ``None``; suffixes are
    lowercased so ``"FOO.PY"`` and ``"foo.py"`` produce the same
    value.
    """
    if not target:
        return None
    suffix = Path(target).suffix
    if not suffix:
        return None
    return suffix.lower()


# ─────────────────────────────────────────────────────────────────────
# Destination probing
# ─────────────────────────────────────────────────────────────────────

# Action families whose ``intent.target`` is a real host path the
# pipeline can stat() directly.  WRITE_FILE is NOT in this set — its
# target is a VFS virtual path whose real-path resolution requires the
# executor's MountPointResolver, which this stage does not hold.
_HOST_PATH_ACTIONS: frozenset[str] = frozenset({
    ActionType.WRITE_HOST_FILE.value,
})


def _kind_from_stat(mode: int) -> FILE_DESTINATION_KIND:
    """Collapse a ``stat.st_mode`` into a FileIntel destination-kind enum.

    Symlinks are NOT represented here — the caller handles them above
    this helper because the "is this a symlink?" question requires
    ``lstat``, not ``stat``.  This function is called with the result
    of ``stat`` (which follows symlinks) so the mode describes the
    link's TARGET, not the link itself.
    """
    if _stat_mod.S_ISREG(mode):
        return "file"
    if _stat_mod.S_ISDIR(mode):
        return "directory"
    return "other"


def _classify_parent_kind(parent: Path) -> FILE_PARENT_KIND:
    """What is at *parent* right now? missing / directory / file / other.

    ``missing`` means the write will implicitly create a directory
    tree.  ``file`` means the parent path is a regular file.  Any
    other OS error collapses to ``other``.
    """
    try:
        st = os.stat(parent)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "other"
    if _stat_mod.S_ISDIR(st.st_mode):
        return "directory"
    if _stat_mod.S_ISREG(st.st_mode):
        return "file"
    return "other"


def build_destination_intel(action_value: str, target: str | None) -> dict:
    """Destination-side FileIntel fields for *target*, as a dict.

    Always returns a dict with the full set of destination / parent /
    path-semantic / relational keys so callers can splat it into
    ``FileIntel(...)`` without per-field defaulting.  Every OS-level
    error is caught and collapsed to ``None`` / default values — the
    function is infallible by design.

    ``extension`` and ``path_category`` come from the target string
    alone and are populated for every action family (including
    ``WRITE_FILE``).  ``destination_*``, ``is_symlink``,
    ``symlink_target_real_path``, ``parent_kind`` require stat-level
    access to a real host path and are populated only for
    :data:`_HOST_PATH_ACTIONS` — for ``WRITE_FILE`` they stay ``None``
    / default.  ``hits_floor_deny_prefix`` runs against the canonicalized
    path string for both families.
    """
    extension = extension_of(target)
    path_category = classify_path_category(target)

    out: dict = {
        "extension": extension,
        "path_category": path_category,
        "destination_exists": None,
        "destination_kind": None,
        "is_symlink": False,
        "symlink_target_real_path": None,
        "parent_kind": None,
        "hits_floor_deny_prefix": False,
    }

    if not target:
        return out

    try:
        canonical = canonicalize_real_path(target)
    except Exception:  # noqa: BLE001 — never let canonicalization fail the pipeline
        logger.debug("FileIntel: canonicalize_real_path raised for %r", target)
        canonical = ""

    if canonical:
        out["hits_floor_deny_prefix"] = match_deny_prefix(canonical) is not None

    # Only stat() for action families whose targets are real host
    # paths.  A virtual target would stat as "missing" against the
    # host root even when the VFS-resolved real path exists, which
    # would be actively misleading — so destination_* stays
    # ``None`` for WRITE_FILE.
    if action_value not in _HOST_PATH_ACTIONS:
        return out

    # For the ``lstat`` probe we want to see the *leaf* symlink if one
    # exists, so we must NOT pass the canonicalized path —
    # ``canonicalize_real_path`` runs ``Path.resolve`` which follows
    # symlinks and would mask ``is_symlink=True``.  Expand ``~`` but
    # leave the symlink intact.  The floor-deny check above already
    # got the canonicalized form, which is what it needs (symlink
    # escapes must canonicalize through their targets to match).
    p = Path(os.path.expanduser(target))
    try:
        lst = os.lstat(p)
    except (FileNotFoundError, NotADirectoryError):
        # Both outcomes mean "nothing is at the target" — either the
        # leaf is missing, or an ancestor is not a directory and so
        # the leaf cannot exist.  ``parent_kind`` preserves the parent
        # state separately.
        out["destination_exists"] = False
        out["destination_kind"] = "missing"
        out["parent_kind"] = _classify_parent_kind(p.parent)
        return out
    except OSError:
        logger.debug(
            "FileIntel: lstat failed for %r — leaving destination unknown",
            target,
        )
        return out

    is_symlink = _stat_mod.S_ISLNK(lst.st_mode)
    out["is_symlink"] = is_symlink

    if is_symlink:
        # Separate the "resolves" and "dangling" branches: a resolving
        # symlink reports destination_kind for what the link points
        # to; a dangling symlink reports ``"symlink"``.
        try:
            st = os.stat(p)
        except (FileNotFoundError, OSError):
            out["destination_exists"] = True
            out["destination_kind"] = "symlink"
            try:
                out["symlink_target_real_path"] = os.readlink(p)
            except OSError:
                pass
            return out
        out["symlink_target_real_path"] = str(p.resolve(strict=False))
        out["destination_exists"] = True
        out["destination_kind"] = _kind_from_stat(st.st_mode)
        return out

    out["destination_exists"] = True
    out["destination_kind"] = _kind_from_stat(lst.st_mode)
    return out


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────


def build_file_intel(
    content: str,
    target: str | None,
    action_value: str,
) -> FileIntel:
    """Build a complete :class:`FileIntel` for a WRITE_FILE-family intent.

    The full :class:`command_shield.CodeReport` stays local to this
    function; the returned ``FileIntel`` carries only a bounded summary.
    Field-size bounds are enforced by :class:`FileIntel` itself on
    construction.

    ``target`` is passed as ``source_path`` to ``inspect_code`` so
    extension-based language sniffing works (e.g. a ``.py`` virtual
    path tells the sniffer to AST-parse before falling back to content
    heuristics).  ``action_value`` decides whether destination probing
    uses host-path stat calls (``WRITE_HOST_FILE``) or leaves
    destination-side fields at their defaults (``WRITE_FILE``).

    Exceptions from the payload inspector return a minimal ``FileIntel``
    with destination fields preserved.  Destination probing is
    independently best-effort; OS errors leave destination-state fields
    at their defaults rather than propagating.
    """
    destination = build_destination_intel(action_value, target)

    try:
        report = shield_inspect_code(content, source_path=target)
    except Exception:  # noqa: BLE001 — defensive; log and return minimal intel
        logger.exception("FileIntel: inspect_code raised — using empty intel")
        return FileIntel(
            language=None,
            is_binary=False,
            is_oversized=False,
            size_bytes=len(content.encode("utf-8", errors="replace")),
            **destination,
        )

    signal_ids = tuple(s.signal_id for s in report.signals)
    is_oversized = "CODE_TOO_LARGE" in signal_ids
    is_binary = report.language == "binary"

    finding_ids: tuple[str, ...] = ()
    if report.code_intel is not None and report.code_intel.findings:
        finding_ids = tuple(
            getattr(f, "finding_id", "") for f in report.code_intel.findings
        )

    return FileIntel(
        language=report.language,
        is_binary=is_binary,
        is_oversized=is_oversized,
        size_bytes=len(content.encode("utf-8", errors="replace")),
        has_code_intel_findings=bool(finding_ids),
        code_intel_finding_ids=finding_ids,
        signal_ids=signal_ids,
        **destination,
    )
