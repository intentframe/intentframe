"""Backward-compatible re-export — implementation lives in action bundle."""

import intentframe_action_bundle.files.file_intel as _impl
from intentframe_action_bundle.files.actions import WRITE_FILE_ACTIONS
from intentframe_action_bundle.files.file_intel import (
    build_destination_intel,
    build_file_intel,
    extension_of,
)

# Mirror module-level bindings so tests can patch intentframe_server.file_intel.*
os = _impl.os
Path = _impl.Path
_stat_mod = _impl._stat_mod
shield_inspect_code = _impl.shield_inspect_code
logger = _impl.logger
_HOST_PATH_ACTIONS = _impl._HOST_PATH_ACTIONS

__all__ = [
    "WRITE_FILE_ACTIONS",
    "build_file_intel",
    "build_destination_intel",
    "extension_of",
]
