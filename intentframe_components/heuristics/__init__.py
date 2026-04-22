"""
Shared, side-effect-free destination classification helpers.

The functions exported here accept a target path string and return
small, deterministic classifications derived from substring matching
against a shared fragment table.  They perform no I/O and maintain no
state.
"""

from intentframe_components.heuristics.file_payload import (
    SENSITIVE_WRITE_PATH_FRAGMENTS,
    classify_path_category,
    is_sensitive_write_path,
)

__all__ = [
    "SENSITIVE_WRITE_PATH_FRAGMENTS",
    "classify_path_category",
    "is_sensitive_write_path",
]
