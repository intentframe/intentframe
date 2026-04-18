"""Conversation history persistence and compaction.

Stores history as JSONL at ~/.jarvis/sessions/current.jsonl.
Compacts old messages by summarising via LLM when the context window
budget is exceeded, flushing notable facts to memory beforehand.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tiktoken
from loguru import logger

if TYPE_CHECKING:
    from jarvis.memory import MemoryManager

from jarvis.config import JarvisConfig


class Session:
    """Manages a single conversation session with JSONL persistence."""

    def __init__(self, sessions_dir: Path, config: JarvisConfig) -> None:
        self.sessions_dir = sessions_dir
        self.path = sessions_dir / "current.jsonl"
        self.archive_dir = sessions_dir / "archive"
        self.config = config
        self.history: list[dict[str, Any]] = []
        self.compaction_count: int = 0
        self._load()

    # -- public API ----------------------------------------------------------

    def append_user(self, message: str) -> None:
        """Append a user message to history."""
        self.history.append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()

    def append_assistant(self, message: str) -> None:
        """Append an assistant message to history."""
        self.history.append({
            "role": "assistant",
            "content": message,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()

    def to_openai_messages(self) -> list[dict[str, Any]]:
        """Return history formatted for the OpenAI chat completions API."""
        return [{"role": m["role"], "content": m["content"]} for m in self.history]

    def estimate_tokens(self) -> int:
        """Count tokens in the current history using tiktoken."""
        try:
            enc = tiktoken.encoding_for_model(self.config.model)
        except KeyError:
            # Fall back to cl100k_base for unknown models
            enc = tiktoken.get_encoding("cl100k_base")
        text = json.dumps(self.history)
        return len(enc.encode(text))

    async def maybe_compact(self, memory_manager: MemoryManager) -> None:
        """Compact history if it exceeds the context-window budget.

        Algorithm:
          1. Compute token budget = context_window * max_history_share.
          2. If current tokens < budget * threshold, do nothing.
          3. Flush notable facts from the old half to MEMORY.md.
          4. Summarise the old half via LLM.
          5. Replace old half with a single summary message + keep recent half.
        """
        budget = int(self.config.context_window_tokens * self.config.max_history_share)
        threshold = int(budget * self.config.compaction_threshold)

        if self.estimate_tokens() < threshold:
            return

        if len(self.history) < 4:
            return  # Too short to compact meaningfully

        mid = len(self.history) // 2
        old_messages = self.history[:mid]
        kept_messages = self.history[mid:]

        logger.info(f"Compacting session: {len(old_messages)} messages → summary")

        # Flush notable facts before they're discarded.
        await memory_manager.memory_flush(old_messages, memory_manager.actor)

        # Summarise old messages.
        summary_text = await self._summarize(old_messages)

        summary_msg: dict[str, Any] = {
            "role": "system",
            "content": f"[Conversation summary — {len(old_messages)} messages]\n{summary_text}",
            "timestamp": datetime.now().isoformat(),
        }

        self.history = [summary_msg] + kept_messages
        self.compaction_count += 1
        self._save()
        logger.info(f"Compaction #{self.compaction_count} complete")

    def reset(self) -> None:
        """Archive the current session and start fresh."""
        if self.history and self.path.exists():
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = self.archive_dir / f"{ts}.jsonl"
            shutil.move(str(self.path), str(dest))
            logger.info(f"Session archived to {dest.name}")
        self.history = []
        self.compaction_count = 0
        self._save()

    # -- internals -----------------------------------------------------------

    def _load(self) -> None:
        """Load history from the JSONL file on disk."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.history = []
            return
        lines = self.path.read_text(encoding="utf-8").splitlines()
        parsed = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"Skipping corrupted session line: {line[:60]!r}")
        self.history = parsed
        logger.debug(f"Loaded {len(self.history)} messages from session")

    def _save(self) -> None:
        """Persist the current history to disk."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for msg in self.history:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    async def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """Summarise a chunk of messages via LLM."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI()

        text_parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            text_parts.append(f"{role.upper()}: {content}")
        conversation = "\n".join(text_parts)

        response = await client.chat.completions.create(
            model=self.config.sub_agent_model,
            max_completion_tokens=1024,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise summariser. Summarise the following conversation "
                        "preserving all facts, decisions, action items, commitments, and "
                        "preferences. Drop filler and small talk. Be terse."
                    ),
                },
                {"role": "user", "content": conversation},
            ],
        )
        return response.choices[0].message.content or ""
