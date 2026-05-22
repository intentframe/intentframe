"""Shared types for action bundle pre-pipeline and deterministic stages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from intentframe_action_bundle.evidence import CommandIntel, FileIntel
from intentframe_core.types import ExecutionResult, IntentFrame


class BundleGateDecision(str, Enum):
    BLOCK = "BLOCK"
    ALLOW = "ALLOW"


@dataclass(frozen=True)
class BundleGateResult:
    decision: BundleGateDecision
    reason: str
    matched_gate: str


@dataclass
class PrePipelineResult:
    """Outputs from the action-agnostic pre-pipeline phase."""

    intent: IntentFrame
    command_intel: CommandIntel | None = None
    file_intel: FileIntel | None = None
    terminal_command_signals: tuple = ()
    early_block: ExecutionResult | None = None
    audit_entry: dict[str, Any] | None = None


@dataclass(frozen=True)
class BundleDeterministicContext:
    """Evidence produced during pre-pipeline, consumed by bundle deterministic gates."""

    command_intel: CommandIntel | None = None
    file_intel: FileIntel | None = None
