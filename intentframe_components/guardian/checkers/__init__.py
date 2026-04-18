"""
Guardian constraint checkers — deterministic per-category enforcement.

Each checker pairs with a constraint data model:
    FileConstraints   → FileChecker
    TerminalConstraints → TerminalChecker
    EmailConstraints  → EmailChecker
    ...

Guardian dispatches via CONSTRAINT_CHECKERS dict lookup,
mirroring the DOMAIN_MODULES pattern from guardian/domains/.
"""

from __future__ import annotations

from intentframe_components.guardian.checkers.base import CheckContext, ConstraintChecker
from intentframe_components.guardian.checkers.file import FileChecker
from intentframe_components.guardian.checkers.terminal import TerminalChecker
from intentframe_components.guardian.checkers.email import EmailChecker
from intentframe_components.guardian.checkers.message import MessageChecker
from intentframe_components.guardian.checkers.browser import BrowserChecker
from intentframe_components.guardian.checkers.api import ApiChecker

from policy_registry.constraints import (
    ApiConstraints,
    BrowserConstraints,
    EmailConstraints,
    FileConstraints,
    MessageConstraints,
    TerminalConstraints,
)

CONSTRAINT_CHECKERS: dict[type, ConstraintChecker] = {
    FileConstraints: FileChecker(),
    TerminalConstraints: TerminalChecker(),
    EmailConstraints: EmailChecker(),
    MessageConstraints: MessageChecker(),
    BrowserConstraints: BrowserChecker(),
    ApiConstraints: ApiChecker(),
}

__all__ = [
    "CONSTRAINT_CHECKERS",
    "CheckContext",
    "ConstraintChecker",
    "ApiChecker",
    "BrowserChecker",
    "EmailChecker",
    "FileChecker",
    "MessageChecker",
    "TerminalChecker",
]
