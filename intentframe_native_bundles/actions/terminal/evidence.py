"""Terminal bundle evidence DTOs and evidence-bag keys."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

COMMAND_INTEL_KEY = "command_intel"
TERMINAL_COMMAND_SIGNALS_KEY = "terminal_command_signals"

COMMAND_INTEL_CAPABILITIES_MAX_ITEMS = 64
COMMAND_INTEL_CAPABILITY_ITEM_MAX_LEN = 128
COMMAND_INTEL_FINDING_IDS_MAX_ITEMS = 32
COMMAND_INTEL_FINDING_ID_MAX_LEN = 96
TERMINAL_COMMAND_SIGNALS_MAX_ITEMS = 32
TERMINAL_COMMAND_SIGNAL_VALUE_MAX_LEN = 300


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
