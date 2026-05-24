"""Build deterministic ``FileIntel`` facts for WRITE_FILE-family actions."""

from __future__ import annotations

import logging
import os
import stat as _stat_mod
from pathlib import Path

from action_registry.types import ActionType
from command_shield import inspect_code as shield_inspect_code
from intentframe_native_bundles.actions.files.path_heuristics import classify_path_category
from intentframe_native_bundles.actions.files.evidence import (
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
    "WRITE_FILE_ACTIONS",
]

from intentframe_native_bundles.actions.files.actions import WRITE_FILE_ACTIONS

_HOST_PATH_ACTIONS: frozenset[str] = frozenset({
    ActionType.WRITE_HOST_FILE.value,
})


def extension_of(target: str | None) -> str | None:
    if not target:
        return None
    suffix = Path(target).suffix
    if not suffix:
        return None
    return suffix.lower()


def _kind_from_stat(mode: int) -> FILE_DESTINATION_KIND:
    if _stat_mod.S_ISREG(mode):
        return "file"
    if _stat_mod.S_ISDIR(mode):
        return "directory"
    return "other"


def _classify_parent_kind(parent: Path) -> FILE_PARENT_KIND:
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
    except Exception:  # noqa: BLE001
        logger.debug("FileIntel: canonicalize_real_path raised for %r", target)
        canonical = ""

    if canonical:
        out["hits_floor_deny_prefix"] = match_deny_prefix(canonical) is not None

    if action_value not in _HOST_PATH_ACTIONS:
        return out

    p = Path(os.path.expanduser(target))
    try:
        lst = os.lstat(p)
    except (FileNotFoundError, NotADirectoryError):
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


def build_file_intel(
    content: str,
    target: str | None,
    action_value: str,
) -> FileIntel:
    destination = build_destination_intel(action_value, target)

    try:
        report = shield_inspect_code(content, source_path=target)
    except Exception:  # noqa: BLE001
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
