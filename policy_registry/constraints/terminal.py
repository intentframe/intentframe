"""Constraints for TERMINAL category actions (RUN_COMMAND)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TerminalConstraints(BaseModel):
    """Command-pattern constraints for terminal/shell actions.

    Two complementary mechanisms:

        blocked_patterns — Substring patterns that are always rejected.
            Checked first. If any pattern appears anywhere in the command
            string, the command is blocked before the allowlist is consulted.
            e.g. ["sudo", "rm -rf /", "mkfs", "dd if=", "chmod 777"]

        allowed_commands — Glob patterns for permitted commands.
            Checked second (only if the command passes the blocklist).
            If non-empty, the command must match at least one pattern.
            If empty, all non-blocked commands are allowed.
            e.g. ["ls *", "pwd", "cat *", "python3 *"]

    Blocklist takes priority over allowlist: a command matching both
    a blocked pattern and an allowed glob is still blocked.
    """

    model_config = ConfigDict(frozen=True)

    blocked_patterns: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
