"""Terminal bundle — AE prompt bodies and ids."""

from __future__ import annotations

from typing import Mapping

from intentframe_action_bundle.terminal.prompts_ae import _CRITICAL_RUN_COMMAND

AE_PROMPT_BODIES: Mapping[str, str] = {
    "critical_run_command": _CRITICAL_RUN_COMMAND,
    "critical_network_probe": _CRITICAL_RUN_COMMAND,
    "critical_network_mutation": _CRITICAL_RUN_COMMAND,
}
