"""Bundle-owned deterministic evidence DTOs (command_shield / file_intel summaries).

``FileIntel`` is shared by the virtual ``files/`` and ``host_files/`` families;
``CommandIntel`` is owned by ``terminal/``. Family folders build these DTOs;
the SDK stores them opaquely in ``BundleContext.evidence``.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

COMMAND_INTEL_CAPABILITIES_MAX_ITEMS = 64
COMMAND_INTEL_CAPABILITY_ITEM_MAX_LEN = 128
COMMAND_INTEL_FINDING_IDS_MAX_ITEMS = 32
COMMAND_INTEL_FINDING_ID_MAX_LEN = 96
TERMINAL_COMMAND_SIGNALS_MAX_ITEMS = 32
TERMINAL_COMMAND_SIGNAL_VALUE_MAX_LEN = 300

FILE_INTEL_LANGUAGE_MAX_LEN = 32
FILE_INTEL_SIGNAL_IDS_MAX_ITEMS = 16
FILE_INTEL_SIGNAL_ID_MAX_LEN = 96
FILE_INTEL_FINDING_IDS_MAX_ITEMS = 32
FILE_INTEL_FINDING_ID_MAX_LEN = 96
FILE_INTEL_PATH_MAX_LEN = 512
FILE_INTEL_EXTENSION_MAX_LEN = 32

FILE_PATH_CATEGORY = Literal[
    "system_config",
    "shell_init",
    "launch_agent",
    "credential_store",
    "persistence_hook",
    "user_document",
    "dev_workspace",
    "cache_or_tmp",
    "unknown",
]

FILE_DESTINATION_KIND = Literal[
    "file",
    "directory",
    "symlink",
    "missing",
    "other",
]

FILE_PARENT_KIND = Literal[
    "directory",
    "missing",
    "file",
    "other",
]


class CommandIntel(BaseModel):
    """Bounded summary of command_shield output for RUN_COMMAND."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["SAFE", "NEEDS_REVIEW", "CATASTROPHIC"] = "SAFE"
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    has_code_intel_findings: bool = False
    code_intel_finding_ids: tuple[str, ...] = Field(default_factory=tuple)
    has_edge_signals: bool = False

    @classmethod
    def _clip_tuple(
        cls,
        values: tuple[str, ...] | list[str] | None,
        max_items: int,
        max_item_len: int,
    ) -> tuple[str, ...]:
        if not values:
            return ()
        clipped: list[str] = []
        for v in values[:max_items]:
            s = str(v)
            if len(s) > max_item_len:
                s = s[:max_item_len]
            clipped.append(s)
        return tuple(clipped)

    def __init__(self, **data: Any) -> None:
        if "capabilities" in data:
            data["capabilities"] = self._clip_tuple(
                data["capabilities"],
                COMMAND_INTEL_CAPABILITIES_MAX_ITEMS,
                COMMAND_INTEL_CAPABILITY_ITEM_MAX_LEN,
            )
        if "code_intel_finding_ids" in data:
            data["code_intel_finding_ids"] = self._clip_tuple(
                data["code_intel_finding_ids"],
                COMMAND_INTEL_FINDING_IDS_MAX_ITEMS,
                COMMAND_INTEL_FINDING_ID_MAX_LEN,
            )
        super().__init__(**data)


class FileIntel(BaseModel):
    """Bounded summary of inspect_code + destination probe for WRITE_FILE."""

    model_config = ConfigDict(frozen=True)

    language: Optional[str] = None
    is_binary: bool = False
    is_oversized: bool = False
    size_bytes: int = 0
    has_code_intel_findings: bool = False
    code_intel_finding_ids: tuple[str, ...] = Field(default_factory=tuple)
    signal_ids: tuple[str, ...] = Field(default_factory=tuple)
    destination_exists: Optional[bool] = None
    destination_kind: Optional[FILE_DESTINATION_KIND] = None
    is_symlink: bool = False
    symlink_target_real_path: Optional[str] = None
    parent_kind: Optional[FILE_PARENT_KIND] = None
    path_category: Optional[FILE_PATH_CATEGORY] = None
    hits_floor_deny_prefix: bool = False
    extension: Optional[str] = None

    @classmethod
    def _clip_tuple(
        cls,
        values: tuple[str, ...] | list[str] | None,
        max_items: int,
        max_item_len: int,
    ) -> tuple[str, ...]:
        if not values:
            return ()
        clipped: list[str] = []
        for v in values[:max_items]:
            s = str(v)
            if len(s) > max_item_len:
                s = s[:max_item_len]
            clipped.append(s)
        return tuple(clipped)

    @classmethod
    def _clip_string(cls, value: Optional[str], max_len: int) -> Optional[str]:
        if value is None:
            return None
        s = str(value)
        return s[:max_len] if len(s) > max_len else s

    def __init__(self, **data: Any) -> None:
        if "language" in data:
            data["language"] = self._clip_string(
                data["language"], FILE_INTEL_LANGUAGE_MAX_LEN
            )
        if "code_intel_finding_ids" in data:
            data["code_intel_finding_ids"] = self._clip_tuple(
                data["code_intel_finding_ids"],
                FILE_INTEL_FINDING_IDS_MAX_ITEMS,
                FILE_INTEL_FINDING_ID_MAX_LEN,
            )
        if "signal_ids" in data:
            data["signal_ids"] = self._clip_tuple(
                data["signal_ids"],
                FILE_INTEL_SIGNAL_IDS_MAX_ITEMS,
                FILE_INTEL_SIGNAL_ID_MAX_LEN,
            )
        if "size_bytes" in data:
            try:
                n = int(data["size_bytes"])
            except (TypeError, ValueError):
                n = 0
            data["size_bytes"] = max(0, n)
        if "symlink_target_real_path" in data:
            data["symlink_target_real_path"] = self._clip_string(
                data["symlink_target_real_path"], FILE_INTEL_PATH_MAX_LEN
            )
        if "extension" in data:
            data["extension"] = self._clip_string(
                data["extension"], FILE_INTEL_EXTENSION_MAX_LEN
            )
        super().__init__(**data)


__all__ = [
    "COMMAND_INTEL_CAPABILITIES_MAX_ITEMS",
    "COMMAND_INTEL_CAPABILITY_ITEM_MAX_LEN",
    "COMMAND_INTEL_FINDING_IDS_MAX_ITEMS",
    "COMMAND_INTEL_FINDING_ID_MAX_LEN",
    "TERMINAL_COMMAND_SIGNALS_MAX_ITEMS",
    "TERMINAL_COMMAND_SIGNAL_VALUE_MAX_LEN",
    "FILE_INTEL_LANGUAGE_MAX_LEN",
    "FILE_INTEL_SIGNAL_IDS_MAX_ITEMS",
    "FILE_INTEL_SIGNAL_ID_MAX_LEN",
    "FILE_INTEL_FINDING_IDS_MAX_ITEMS",
    "FILE_INTEL_FINDING_ID_MAX_LEN",
    "FILE_INTEL_PATH_MAX_LEN",
    "FILE_INTEL_EXTENSION_MAX_LEN",
    "FILE_PATH_CATEGORY",
    "FILE_DESTINATION_KIND",
    "FILE_PARENT_KIND",
    "CommandIntel",
    "FileIntel",
]
