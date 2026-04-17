"""Thin back-compat shim around the unified inspection pipeline.

The historical public entry point was ``analyze(command)``.  The real
orchestrator now lives in :mod:`command_shield.pipeline` as
``inspect_command``.  This shim preserves the old name, imports, and
signature so existing callers (pipeline, tests, adapters) keep working.
"""

from __future__ import annotations

from command_shield.config import ShieldConfig
from command_shield.pipeline import inspect_command
from command_shield.verdict import CommandReport


def analyze(
    command: str,
    *,
    file_content: str | None = None,
    file_path: str | None = None,
    config: ShieldConfig | None = None,
) -> CommandReport:
    """Run the full synchronous inspection pipeline.

    Alias for :func:`command_shield.pipeline.inspect_command`.  Retained
    so existing imports (``from command_shield import analyze``) keep
    working.
    """
    return inspect_command(
        command,
        file_content=file_content,
        file_path=file_path,
        config=config,
    )


__all__ = ["analyze"]
