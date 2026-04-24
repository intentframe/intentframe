"""Root-demo flavour of StubPipelineAgent + local fixture loader.

The agent is the existing ``StubPipelineAgent`` with capabilities trimmed to
the four actions exercised by the root-demo profile.  Fixture lookup is
local to ``demo/tests/root_demo/intents/<category>/`` so each category
(normal, attacks, persistence, egress, ...) has its own directory and
dedicated test file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intentframe_core.types import AgentCapabilities

from stub_pipeline_agent import StubPipelineAgent

_ROOT_INTENTS_DIR = Path(__file__).resolve().parent / "intents"


class StubPipelineRootAgent(StubPipelineAgent):
    CAPABILITIES = AgentCapabilities(
        agent_type="StubPipelineRootTest",
        description=(
            "Test harness mirroring the Jarvis root profile, scoped to "
            "RUN_COMMAND, READ/WRITE/LIST_HOST_FILE for adversarial runs."
        ),
        capabilities=["scripted_submits"],
        resource_needs=["root_workspace"],
        action_types=[
            "RUN_COMMAND",
            "WRITE_HOST_FILE",
            "READ_HOST_FILE",
            "LIST_HOST_DIRECTORY",
        ],
        version="1.0.0",
        author="IntentFrame Tests",
    )


def load_root_intents(category: str, intent_num: int) -> list[dict[str, Any]]:
    """Load an intent fixture from ``intents/<category>/<category>_<NN>_*.json``."""
    category_dir = _ROOT_INTENTS_DIR / category
    pattern = f"{category}_{intent_num:02d}_*.json"
    matches = sorted(category_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No intent fixture matching {pattern} in {category_dir}"
        )
    with open(matches[0]) as f:
        data = json.load(f)
    return data["submissions"]
