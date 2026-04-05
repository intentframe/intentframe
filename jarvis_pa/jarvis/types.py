"""Shared types used across the Jarvis codebase."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.config import JarvisConfig
    from jarvis.memory_search import MemorySearcher
    from intentframe_actor import Actor


@dataclass
class AgentContext:
    """Passed to every tool call via RunContextWrapper."""

    actor: Actor
    config: JarvisConfig
    searcher: MemorySearcher
    is_sub_agent: bool = False  # M6: prevents sub-agents from spawning further sub-agents


@dataclass
class SearchResult:
    """A single result from hybrid memory search."""

    chunk_id: str
    path: str
    start_line: int
    end_line: int
    text: str
    score: float


@dataclass
class SkillEntry:
    """Parsed metadata from a SKILL.md frontmatter."""

    name: str
    description: str
    path: Path
    requires_bins: list[str] = field(default_factory=list)
    requires_any_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)
    os_filter: list[str] = field(default_factory=list)
    always: bool = False
