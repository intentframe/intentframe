"""RUN_COMMAND read-only fast-path helpers (lifted from DeterministicGuardian)."""

from __future__ import annotations

from intentframe_core.types import CommandIntel
from policy_registry.constraints._capability_match import any_tag_matches

READ_ONLY_INCOMPATIBLE: frozenset[str] = frozenset({
    "capability:filesystem_write",
    "capability:stdin_exec",
    "capability:network_bind",
    "capability:background_exec",
    "capability:download_and_exec",
    "capability:process_signal",
    "capability:spawns_process",
})


def is_read_only_fast_path(
    intel: CommandIntel,
    deny_caps: frozenset[str],
) -> bool:
    if intel.verdict != "SAFE":
        return False
    caps = set(intel.capabilities)
    if not any(c.startswith("capability:read_only:") for c in caps):
        return False
    if caps & READ_ONLY_INCOMPATIBLE:
        return False
    if any(c.startswith("capability:network_probe:") for c in caps):
        return False
    if any(c.startswith("capability:data_read:") for c in caps):
        return False
    if any(c.startswith("capability:system_mutate:") for c in caps):
        return False
    if deny_caps and any_tag_matches(caps, deny_caps) is not None:
        return False
    if intel.has_edge_signals:
        return False
    if intel.has_code_intel_findings:
        return False
    return True
