"""
Guardian constraint checkers — dispatch via action bundle manifest.

Each checker implementation lives in ``intentframe_action_bundle``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker

if TYPE_CHECKING:
    from policy_registry.constraints import (
        ApiConstraints,
        BrowserConstraints,
        EmailConstraints,
        FileConstraints,
        HostFileConstraints,
        MessageConstraints,
        TerminalConstraints,
    )


class _LazyConstraintCheckers(dict):
    """Populate CONSTRAINT_CHECKERS on first access to break import cycles."""

    _loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        from intentframe_action_bundle.manifest import constraint_checkers

        self.update(constraint_checkers())
        self._loaded = True

    def __getitem__(self, key):
        self._ensure_loaded()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._ensure_loaded()
        return super().get(key, default)

    def __contains__(self, key):
        self._ensure_loaded()
        return super().__contains__(key)


CONSTRAINT_CHECKERS: dict[type, ConstraintChecker] = _LazyConstraintCheckers()

from intentframe_action_bundle.api.checker import ApiChecker
from intentframe_action_bundle.browser.checker import BrowserChecker
from intentframe_action_bundle.email.checker import EmailChecker
from intentframe_action_bundle.files.checker import FileChecker
from intentframe_action_bundle.host_files.checker import HostFileChecker
from intentframe_action_bundle.message.checker import MessageChecker
from intentframe_action_bundle.terminal.checker import TerminalChecker

__all__ = [
    "CONSTRAINT_CHECKERS",
    "CheckContext",
    "ConstraintChecker",
    "ApiChecker",
    "BrowserChecker",
    "EmailChecker",
    "FileChecker",
    "HostFileChecker",
    "MessageChecker",
    "TerminalChecker",
]
