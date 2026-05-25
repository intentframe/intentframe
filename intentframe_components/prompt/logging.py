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

_PROMPT_FILENAMES: dict[PromptLogComponent, str] = {
    "onboarding": "onboarding_prompts.log",
    "analysis": "analysis_prompts.log",
    "guardian": "guardian_prompts.log",
}

_OUTPUT_FILENAMES: dict[PromptLogComponent, str] = {
    "analysis": "analysis_outputs.log",
    "guardian": "guardian_outputs.log",
}


def _log_dir() -> Path:
    log_dir = Path(
        os.environ.get(
            "INTENTFRAME_LOG_DIR",
            os.path.expanduser("~/.intentframe/logs"),
        )
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def log_prompt_dump(
    component: PromptLogComponent,
    prompt: str,
    *,
    prompt_label: str | None = None,
    prompt_source: str | None = None,
    system_prompt: str | None = None,
    bundle_ai_context: dict[str, object] | None = None,
    verbose: bool = False,
) -> None:
    """Append one JSON line containing full prompt evidence."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "prompt_source": prompt_source,
        "prompt_label": prompt_label,
        "system_prompt": system_prompt,
        "request_prompt": prompt,
        "bundle_ai_context": bundle_ai_context,
    }
    line = json.dumps(entry, default=str)

    with (_log_dir() / _PROMPT_FILENAMES[component]).open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("\n")

    if verbose:
        print(line)


def log_output_dump(
    component: PromptLogComponent,
    *,
    llm_output: dict[str, object] | None = None,
    converted_output: dict[str, object] | None = None,
    prompt_source: str | None = None,
    prompt_label: str | None = None,
    verbose: bool = False,
) -> None:
    """Append one JSON line with raw LLM output and converted pipeline artifact.

    Called after ``Runner.run`` so prompt dumps (pre-call) stay in their
    existing order and files.
    """
    if component == "onboarding":
        return
    if llm_output is None and converted_output is None:
        return

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "prompt_source": prompt_source,
        "prompt_label": prompt_label,
        "llm_output": llm_output,
        "converted_output": converted_output,
    }
    line = json.dumps(entry, default=str)

    with (_log_dir() / _OUTPUT_FILENAMES[component]).open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("\n")

    if verbose:
        print(line)

