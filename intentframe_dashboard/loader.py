"""
Agent Package Loader — scans an agent directory and reads manifests.

Each subdirectory with a manifest.yaml is treated as an installable
agent package.  The loader only reads metadata — it never imports
or executes agent code.  That's the Runner's job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import yaml

from intentframe_dashboard.manifest import AgentManifest


def scan_agents(agent_dir: Path) -> Dict[str, AgentManifest]:
    """Discover all agent packages in the given directory.

    Returns a mapping of agent name -> parsed manifest.
    """
    manifests: Dict[str, AgentManifest] = {}
    if not agent_dir.is_dir():
        return manifests

    for child in sorted(agent_dir.iterdir()):
        manifest_path = child / "manifest.yaml"
        if not manifest_path.is_file():
            continue
        with open(manifest_path) as f:
            raw = yaml.safe_load(f)
        manifest = AgentManifest(**raw)
        manifests[manifest.name] = manifest

    return manifests
