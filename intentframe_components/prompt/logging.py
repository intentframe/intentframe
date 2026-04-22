"""
Minimal prompt-dump logging for AI components.

Writes one JSON line per AI call to a component-specific file so
operators can inspect the exact prompt/user-message sent to the model
without adding extra prompt-construction code paths to maintain.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

PromptLogComponent = Literal["onboarding", "analysis", "guardian"]

_FILENAMES: dict[PromptLogComponent, str] = {
    "onboarding": "onboarding_prompts.log",
    "analysis": "analysis_prompts.log",
    "guardian": "guardian_prompts.log",
}


def log_prompt_dump(
    component: PromptLogComponent,
    prompt: str,
    *,
    prompt_id: str | None = None,
    verbose: bool = False,
) -> None:
    """Append one JSON line containing the full prompt string."""
    log_dir = Path(
        os.environ.get(
            "INTENTFRAME_LOG_DIR",
            os.path.expanduser("~/.intentframe/logs"),
        )
    )
    log_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "prompt_id": prompt_id,
        "prompt": prompt,
    }
    line = json.dumps(entry, default=str)

    with (log_dir / _FILENAMES[component]).open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("\n")

    if verbose:
        print(line)

