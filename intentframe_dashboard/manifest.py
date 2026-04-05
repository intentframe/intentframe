"""
Agent Manifest — Pydantic schema for agent package manifests.

Every agent package in external_agents/ must include a manifest.yaml
that declares identity, entry point, runner type, and capabilities.

The manifest is the contract between the dashboard and the program.
The dashboard never imports or inspects the program's code directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CapabilitiesManifest(BaseModel):
    """What the program declares it will do.

    Used by the dashboard for display, pre-validation, and
    permission scoping — NOT for runtime enforcement (that's Guardian).
    """
    agent_type: str = ""
    declared_actions: List[str] = Field(default_factory=list)
    required_resources: List[str] = Field(default_factory=list)
    max_financial_limit: Optional[float] = None


class AgentManifest(BaseModel):
    """APK-like manifest for an installable agent/program."""

    name: str
    version: str = "0.1.0"
    author: str = "unknown"
    description: str = ""

    entry_point: str = Field(
        ...,
        description=(
            "What to execute inside the package directory. "
            "For runner='python': a module path like 'agent.py' or 'agent:main'. "
            "For runner='executable': a binary name."
        ),
    )
    runner: str = Field(
        default="python",
        description="How to launch: 'python' | 'executable' | 'docker'",
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description=(
            "Pip-installable packages the agent needs. "
            "IntentFrame SDK packages (intentframe_core, intentframe_actor, etc.) "
            "are auto-installed by the dashboard."
        ),
    )
    options: Dict[str, Any] = Field(default_factory=dict)

    capabilities: CapabilitiesManifest = Field(
        default_factory=CapabilitiesManifest,
    )
