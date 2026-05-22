"""Deprecated — pre-pipeline is folded into the Bundle SDK lifecycle.

Use DeterministicGuardian (permission → action bundle prepare → …).
"""

from __future__ import annotations

from intentframe_action_bundle.types import PrePipelineResult


async def run_pre_pipeline(intent, *, verbose: bool = False) -> PrePipelineResult:
    """Backward-compatible no-op; pipeline calls DeterministicGuardian directly."""
    del verbose
    return PrePipelineResult(intent=intent)
