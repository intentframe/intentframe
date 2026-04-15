"""Sandbox engine abstract base and factory.

Each platform gets its own ``SandboxEngine`` implementation.  The factory
inspects the resolved platform string and returns the right one (or ``None``
if the platform isn't supported).
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from executor.sandbox.planner import ExecutionPlan


@dataclass(frozen=True)
class SandboxedCommand:
    """Result of wrapping a command for sandboxed execution.

    Callers pass *argv* to ``create_subprocess_exec`` (no shell re-parsing)
    and merge *env_overrides* into the process environment.
    """

    argv: list[str]
    env_overrides: dict[str, str] = field(default_factory=dict)


class SandboxEngine(ABC):
    """Platform-specific sandbox enforcement interface."""

    @abstractmethod
    def available(self) -> bool:
        """Return ``True`` if the sandbox mechanism is usable on this host."""
        ...

    @abstractmethod
    def wrap(self, command: str, plan: ExecutionPlan) -> SandboxedCommand:
        """Wrap *command* so it runs inside the sandbox described by *plan*.

        Returns a ``SandboxedCommand`` whose *argv* is passed directly to
        ``create_subprocess_exec`` — no shell quoting required.
        """
        ...


def create_sandbox_engine(platform: str) -> SandboxEngine | None:
    """Factory: return the appropriate engine for *platform*, or ``None``."""
    resolved = _resolve_platform(platform)
    if resolved == "macos":
        from executor.sandbox.platforms.macos import MacOSSandboxEngine

        return MacOSSandboxEngine()
    return None


def _resolve_platform(platform: str) -> str:
    if platform != "auto":
        return platform.lower()
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform
