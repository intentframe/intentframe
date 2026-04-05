"""Skill discovery, gating, indexing, and lazy loading.

Scans skill directories for SKILL.md files, parses YAML frontmatter
using python-frontmatter, filters by runtime gating checks (required
binaries, env vars, OS), and builds a compact XML index for the system
prompt.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

import frontmatter
from loguru import logger

from jarvis.types import SkillEntry


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_skills(dirs: list[Path]) -> list[SkillEntry]:
    """Scan directories for SKILL.md, parse frontmatter, deduplicate by name.

    Later directories win (user-installed skills override bundled ones).
    """
    found: dict[str, SkillEntry] = {}

    for directory in dirs:
        if not directory.exists():
            continue
        for skill_md in sorted(directory.rglob("SKILL.md")):
            entry = _parse_frontmatter(skill_md)
            if entry is not None:
                found[entry.name] = entry  # later dirs overwrite earlier

    skills = list(found.values())
    logger.debug(f"Discovered {len(skills)} skills across {len(dirs)} directories")
    return skills


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def gate_skills(skills: list[SkillEntry]) -> list[SkillEntry]:
    """Filter skills by runtime conditions.

    Checks (all must pass unless always=True):
      - OS filter (darwin/linux/windows)
      - required bins: ALL must be on PATH
      - any_bins: at least ONE must be on PATH
      - required env vars: ALL must be non-empty in os.environ
    """
    current_os = platform.system().lower()
    gated: list[SkillEntry] = []

    for skill in skills:
        if skill.always:
            gated.append(skill)
            continue

        # OS check
        if skill.os_filter and current_os not in [o.lower() for o in skill.os_filter]:
            logger.debug(f"Skill '{skill.name}' filtered: OS {current_os!r} not in {skill.os_filter}")
            continue

        # Required bins (all must exist)
        missing_bins = [b for b in skill.requires_bins if not shutil.which(b)]
        if missing_bins:
            logger.debug(f"Skill '{skill.name}' filtered: missing bins {missing_bins}")
            continue

        # Any bins (at least one must exist)
        if skill.requires_any_bins and not any(shutil.which(b) for b in skill.requires_any_bins):
            logger.debug(f"Skill '{skill.name}' filtered: none of {skill.requires_any_bins} on PATH")
            continue

        # Required env vars (all must be set and non-empty)
        missing_env = [v for v in skill.requires_env if not os.environ.get(v)]
        if missing_env:
            logger.debug(f"Skill '{skill.name}' filtered: missing env vars {missing_env}")
            continue

        gated.append(skill)

    logger.debug(f"Gated {len(gated)}/{len(skills)} skills passed")
    return gated


# ---------------------------------------------------------------------------
# XML index for system prompt
# ---------------------------------------------------------------------------


def build_skills_xml(skills: list[SkillEntry]) -> str:
    """Build a compact XML index string for injection into the system prompt."""
    if not skills:
        return ""

    lines = ["<skills>"]
    for skill in skills:
        desc = skill.description.replace("<", "&lt;").replace(">", "&gt;")
        path = str(skill.path)
        lines.append(f'  <skill name="{skill.name}" path="{path}">{desc}</skill>')
    lines.append("</skills>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> SkillEntry | None:
    """Read a SKILL.md and extract YAML frontmatter into a SkillEntry."""
    try:
        post = frontmatter.load(str(path))
    except Exception as exc:
        logger.warning(f"Failed to parse {path}: {exc}")
        return None

    meta = post.metadata
    name = meta.get("name")
    description = meta.get("description", "")

    if not name:
        logger.debug(f"Skipping {path}: no 'name' in frontmatter")
        return None

    requires = meta.get("metadata", {}).get("requires", {})
    if not requires:
        # Also support top-level requires key
        requires = meta.get("requires", {})

    os_filter = meta.get("metadata", {}).get("os", meta.get("os", []))
    always = bool(meta.get("always", meta.get("metadata", {}).get("always", False)))

    return SkillEntry(
        name=str(name),
        description=str(description),
        path=path,
        requires_bins=requires.get("bins", []),
        requires_any_bins=requires.get("anyBins", requires.get("any_bins", [])),
        requires_env=requires.get("env", []),
        os_filter=os_filter if isinstance(os_filter, list) else [os_filter],
        always=always,
    )
