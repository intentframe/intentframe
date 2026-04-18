"""Workspace file management, auto-capture, and memory flush.

Manages the ~/.jarvis/workspace/ directory:
  SOUL.md, USER.md, MEMORY.md, HEARTBEAT.md, memory/*.md (daily logs).

Handles first-run bootstrap (copying bundled templates), auto-capturing
notable facts from conversation turns, and flushing knowledge during
context compaction.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from intentframe_actor import Actor

from jarvis.config import JarvisConfig

# ---------------------------------------------------------------------------
# Auto-capture trigger patterns
# ---------------------------------------------------------------------------

MEMORY_TRIGGERS: list[re.Pattern[str]] = [
    re.compile(r"remember", re.IGNORECASE),
    re.compile(r"prefer|i like|i hate|i love|i want|i need", re.IGNORECASE),
    re.compile(r"always|never|important", re.IGNORECASE),
    re.compile(r"my\s+\w+\s+is|is\s+my", re.IGNORECASE),
    re.compile(r"[\w.-]+@[\w.-]+\.\w+"),
    re.compile(r"\+\d{10,}"),
    re.compile(r"we decided|we agreed|let'?s use", re.IGNORECASE),
]

# Bundled workspace templates live next to this file.
_BUNDLED_WORKSPACE = Path(__file__).parent / "workspace"


class MemoryManager:
    """Owns the workspace directory and all memory-related operations."""

    def __init__(self, workspace_dir: Path, actor: Any, config: JarvisConfig) -> None:
        self.workspace = workspace_dir
        self.actor = actor
        self.config = config
        self.files_changed: bool = False

    # -- bootstrap -----------------------------------------------------------

    async def bootstrap_if_needed(self) -> None:
        """Copy bundled templates to workspace on first run."""
        soul_target = self.workspace / "SOUL.md"
        if soul_target.exists():
            logger.debug("Workspace already bootstrapped — skipping")
            return  # Already bootstrapped

        self.workspace.mkdir(parents=True, exist_ok=True)
        # Copy every file from the bundled workspace/ directory.
        for src in _BUNDLED_WORKSPACE.iterdir():
            if src.is_file():
                dest = self.workspace / src.name
                if not dest.exists():
                    dest.write_bytes(src.read_bytes())

        # Ensure required runtime subdirectories exist.
        (self.workspace.parent / "sessions" / "archive").mkdir(parents=True, exist_ok=True)
        (self.workspace.parent / "index").mkdir(parents=True, exist_ok=True)
        (self.workspace.parent / "skills").mkdir(parents=True, exist_ok=True)
        (self.workspace / "memory").mkdir(parents=True, exist_ok=True)
        logger.info(f"Workspace bootstrapped at {self.workspace}")

    # -- file reading --------------------------------------------------------

    async def read_file(self, name: str) -> str:
        """Read a workspace file by name (e.g. 'SOUL.md'). Returns '' if missing."""
        target = self.workspace / name
        if target.exists():
            return target.read_text(encoding="utf-8")
        return ""

    # -- auto-capture --------------------------------------------------------

    def auto_capture(self, user_message: str, assistant_message: str) -> None:
        """Check trigger patterns and append to today's daily log if matched."""
        combined = f"{user_message}\n{assistant_message}"
        if not self.should_capture(combined, self.config.auto_capture_min_len, self.config.auto_capture_max_len):
            return

        category = self.detect_category(combined)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = self.workspace / "memory" / f"{today}.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%H:%M")
        entry = (
            f"\n### {ts} [{category}]\n"
            f"**User:** {user_message[:200]}\n"
            f"**Jarvis:** {assistant_message[:200]}\n"
        )
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
        self.files_changed = True
        logger.debug(f"Auto-captured [{category}] to {log_path.name}")

    # -- memory flush (called during compaction) -----------------------------

    async def memory_flush(self, dropped_messages: list[dict[str, Any]], actor: Any) -> None:
        """Extract notable facts from dropped messages and append to MEMORY.md."""
        if not dropped_messages:
            return

        extract_prompt = (
            "Extract notable facts worth remembering long-term from this conversation: "
            "preferences, decisions, commitments, entities (names/emails/numbers), "
            "or important context. Be concise — one bullet per fact. "
            "If nothing is worth keeping, reply with exactly: NOTHING"
        )

        try:
            facts = await self._extract_notable(dropped_messages, extract_prompt)
        except Exception as exc:
            logger.warning(f"memory_flush extraction failed: {exc}")
            return

        if not facts or facts.strip().upper() == "NOTHING":
            return

        memory_path = self.workspace / "MEMORY.md"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n\n### Auto-captured {ts}\n{facts.strip()}\n"

        with memory_path.open("a", encoding="utf-8") as f:
            f.write(entry)
        self.files_changed = True
        logger.info(f"Memory flush: {len(facts.split(chr(10)))} lines written to MEMORY.md")

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def should_capture(text: str, min_len: int = 10, max_len: int = 500) -> bool:
        """Return True if text matches any auto-capture trigger."""
        if len(text) < min_len or len(text) > max_len:
            return False
        # Exclude XML/HTML-heavy content
        if re.search(r"<[a-z][^>]{0,50}>", text, re.IGNORECASE):
            return False
        return any(pattern.search(text) for pattern in MEMORY_TRIGGERS)

    @staticmethod
    def detect_category(text: str) -> str:
        """Classify captured text into: preference, decision, entity, fact, other."""
        text_lower = text.lower()
        if any(w in text_lower for w in ("prefer", "like", "hate", "love", "want", "need")):
            return "preference"
        if any(w in text_lower for w in ("decided", "agreed", "let's use", "we will")):
            return "decision"
        if re.search(r"[\w.-]+@[\w.-]+\.\w+|\+\d{10,}", text):
            return "entity"
        if any(w in text_lower for w in ("always", "never", "important", "remember")):
            return "fact"
        return "other"

    async def _extract_notable(self, messages: list[dict[str, Any]], prompt: str) -> str:
        """Call LLM to extract notable facts from messages."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI()

        text_parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            text_parts.append(f"{role.upper()}: {content[:400]}")
        conversation = "\n".join(text_parts)

        response = await client.chat.completions.create(
            model=self.config.sub_agent_model,
            max_completion_tokens=512,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": conversation},
            ],
        )
        return response.choices[0].message.content or ""
