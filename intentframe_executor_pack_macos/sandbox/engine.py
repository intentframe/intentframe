"""Public sandbox engine contract for executor packs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .plan import ExecutionPlan


@dataclass(frozen=True)
class SandboxedCommand:
    """Command argv and environment overrides produced by a sandbox engine."""

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
        """Wrap *command* so it runs inside the sandbox described by *plan*."""
        ...
