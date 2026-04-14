"""Sandbox engine abstract base and factory.

Each platform gets its own ``SandboxEngine`` implementation.  The factory
inspects the resolved platform string and returns the right one (or ``None``
if the platform isn't supported).
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod

from executor.sandbox.planner import ExecutionPlan


class SandboxEngine(ABC):
    """Platform-specific sandbox enforcement interface."""

    @abstractmethod
    def available(self) -> bool:
        """Return ``True`` if the sandbox mechanism is usable on this host."""
        ...

    @abstractmethod
    def wrap(self, command: str, plan: ExecutionPlan) -> str:
        """Wrap *command* so it runs inside the sandbox described by *plan*.

        Returns a shell-ready string (the caller passes it to
        ``create_subprocess_shell``).
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
