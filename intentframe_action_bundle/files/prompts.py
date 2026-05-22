"""Files bundle — AE prompt bodies and ids."""

from __future__ import annotations

from typing import Mapping

from intentframe_action_bundle.files.prompts_ae import _CRITICAL_WRITE_FILE

AE_PROMPT_BODIES: Mapping[str, str] = {
    "critical_write_file": _CRITICAL_WRITE_FILE,
}
