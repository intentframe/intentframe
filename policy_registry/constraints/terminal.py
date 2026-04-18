"""Constraints for TERMINAL category actions (RUN_COMMAND)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TerminalConstraints(BaseModel):
    """Command-pattern constraints for terminal/shell actions.

    Four complementary mechanisms, evaluated in order:

        1. blocked_patterns — Substring patterns that are always rejected.
            Checked first. If any pattern appears anywhere in the command
            string, the command is blocked before any other check.
            e.g. ["sudo", "rm -rf /", "mkfs", "dd if=", "chmod 777"]

        2. deny_capabilities — Structured capability tags that are never
            allowed, regardless of what else matches.  Tags come from
            command_shield's classifier (e.g.
            ``capability:package_install:pip``,
            ``capability:network_bind``).  Supports exact and
            ``capability:<family>:*`` prefix-glob patterns.
            A command whose CommandIntel capabilities match any deny
            pattern is BLOCKed.

        3. allowed_commands — Glob patterns for permitted commands.
            Checked third (only if the command passes blocklist and
            deny-caps).  If non-empty, the command must match at least
            one pattern.  If empty, all non-blocked commands are allowed.
            e.g. ["ls *", "pwd", "cat *", "python3 *"]

        4. allow_capabilities — Structured tag allowlist.  When non-empty,
            every emitted capability on the command must match at least
            one allow pattern; unknown tags imply the command is broader
            than the policy permits and it is BLOCKed.  When empty,
            capabilities are not used to gate admission (blocklist +
            allowlist still apply).

    Evaluation order above mirrors TerminalChecker.check() and encodes
    the "blocklist beats allowlist" invariant: a command matching both
    a blocked pattern and an allowed glob is still blocked.  The same
    is true for capability-level deny.

    Why frozenset for capability sets (not set):
        ``model_config = ConfigDict(frozen=True)`` freezes the field
        reassignment, but NOT the in-place mutation of mutable
        containers.  ``frozenset`` enforces true immutability for
        policy-snapshot semantics, matching the "policies are
        snapshotted at task start" invariant in the policy enforcement
        model.
    """

    model_config = ConfigDict(frozen=True)

    blocked_patterns: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
    allow_capabilities: frozenset[str] = Field(default_factory=frozenset)
    deny_capabilities: frozenset[str] = Field(default_factory=frozenset)
