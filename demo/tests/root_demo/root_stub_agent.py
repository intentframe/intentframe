"""Root-demo flavour of StubPipelineAgent + local fixture loader.

The agent is the existing ``StubPipelineAgent`` with capabilities trimmed
to ``RUN_COMMAND``.  Root operations on a real computer are shell
operations, and the sandbox engine's ``sudo -n`` escalation only wraps
RUN_COMMAND -- granting other adapters here would be a category mismatch
(and they wouldn't escalate anyway).  Fixture lookup is local to
``demo/tests/root_demo/intents/<category>/`` so each category (normal,
attacks, persistence, egress, ...) has its own directory and dedicated
test file.
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
            "RUN_COMMAND -- root operations are shell operations, and "
            "RUN_COMMAND is the only adapter that escalates via the "
            "sandbox engine."
        ),
        capabilities=["scripted_submits"],
        resource_needs=["root_workspace"],
        action_types=["RUN_COMMAND"],
        version="1.0.0",
        author="IntentFrame Tests",
    )


def load_root_intent_fixture(category: str, intent_num: int) -> dict[str, Any]:
    """Load the full intent fixture JSON from ``intents/<category>/<category>_<NN>_*.json``.

    Returns the parsed JSON dict verbatim so callers that need
    benign-suite extras (``cleanup``, ``reversible``, ``attack_counterpart``)
    can read them without re-opening the file.
    """
    category_dir = _ROOT_INTENTS_DIR / category
    pattern = f"{category}_{intent_num:02d}_*.json"
    matches = sorted(category_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No intent fixture matching {pattern} in {category_dir}"
        )
    with open(matches[0]) as f:
        return json.load(f)


def load_root_intents(category: str, intent_num: int) -> list[dict[str, Any]]:
    """Load an intent fixture's ``submissions`` list (thin wrapper)."""
    return load_root_intent_fixture(category, intent_num)["submissions"]
