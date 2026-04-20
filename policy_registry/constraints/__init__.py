"""
Per-category constraint schemas.

Each action category has its own constraint model reflecting
the nature of actions in that category.  File actions need path
constraints, email actions need recipient constraints, etc.

These are pure data definitions — the Policy Registry stores them,
consumers (like IntentFrame's Guardian) evaluate them.
"""

from policy_registry.constraints.file import FileConstraints
from policy_registry.constraints.host_file import HostFileConstraints
from policy_registry.constraints.terminal import TerminalConstraints
from policy_registry.constraints.email import EmailConstraints, RecipientSource
from policy_registry.constraints.calendar import CalendarConstraints
from policy_registry.constraints.message import MessageConstraints, ContactSource
from policy_registry.constraints.browser import BrowserConstraints
from policy_registry.constraints.api import ApiConstraints

__all__ = [
    "ApiConstraints",
    "BrowserConstraints",
    "CalendarConstraints",
    "ContactSource",
    "EmailConstraints",
    "FileConstraints",
    "HostFileConstraints",
    "MessageConstraints",
    "RecipientSource",
    "TerminalConstraints",
]
