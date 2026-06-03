"""
Action Registry — core types.

Defines the universal action taxonomy: categories, types, domain tags, and
metadata mappings (``ACTION_CATEGORIES``, ``ACTION_DOMAINS``). No enforcement
logic — bundles and the Guardian consume these definitions at runtime.

``ActionType`` subclasses ``str`` so enum members are interchangeable with
the plain ``str`` on :attr:`~intentframe_bundle_sdk.IntentFrame.action`.
Platform-only actions (``RUN_SHORTCUT``, …) may exist in :class:`ActionCatalog`
without being enum members; they still flow as strings through the pipeline.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ActionCategory(Enum):
    """Broad groupings of actions by nature.

    Each ActionType belongs to exactly one category.
    Categories determine which constraint schema applies in the Policy Registry.
    """

    FILE = "FILE"
    HOST_FILE = "HOST_FILE"
    TERMINAL = "TERMINAL"
    EMAIL = "EMAIL"
    CALENDAR = "CALENDAR"
    REMINDERS = "REMINDERS"
    CONTACTS = "CONTACTS"
    NOTES = "NOTES"
    MESSAGES = "MESSAGES"
    BROWSER = "BROWSER"
    CLIPBOARD = "CLIPBOARD"
    SEARCH = "SEARCH"
    NOTIFICATION = "NOTIFICATION"
    API = "API"
    USER_IO = "USER_IO"
    SYSTEM = "SYSTEM"


class ActionType(str, Enum):
    """Canonical action types available on the device.

    Universal actions exist on every platform.
    Platform-specific actions are registered via platform modules.

    Subclasses ``str`` so members are drop-in string identifiers: an
    ``ActionType`` member equals its ``.value`` and can populate the plain
    ``str`` ``IntentFrame.action`` field directly. Substrate and internal
    ``intentframe_core`` stay decoupled from this taxonomy.
    """

    # ── FILE ──────────────────────────────────────────────────────
    LIST_DIRECTORY = "LIST_DIRECTORY"
    READ_FILE = "READ_FILE"
    WRITE_FILE = "WRITE_FILE"
    APPEND_ROW = "APPEND_ROW"
    DELETE_FILE = "DELETE_FILE"

    # ── HOST_FILE ─────────────────────────────────────────────────
    # Real-path operations parallel to FILE actions. Uses host OS paths
    # (e.g. ~/Documents/...) rather than the virtual filesystem.
    READ_HOST_FILE = "READ_HOST_FILE"
    WRITE_HOST_FILE = "WRITE_HOST_FILE"
    DELETE_HOST_FILE = "DELETE_HOST_FILE"
    LIST_HOST_DIRECTORY = "LIST_HOST_DIRECTORY"

    # ── TERMINAL ──────────────────────────────────────────────────
    RUN_COMMAND = "RUN_COMMAND"

    # ── EMAIL ─────────────────────────────────────────────────────
    SEND_EMAIL = "SEND_EMAIL"
    READ_EMAIL = "READ_EMAIL"
    SEARCH_EMAIL = "SEARCH_EMAIL"
    GET_EMAIL = "GET_EMAIL"
    REPLY_EMAIL = "REPLY_EMAIL"
    FORWARD_EMAIL = "FORWARD_EMAIL"
    MARK_READ_EMAIL = "MARK_READ_EMAIL"
    MOVE_EMAIL = "MOVE_EMAIL"
    DELETE_EMAIL = "DELETE_EMAIL"
    DOWNLOAD_ATTACHMENT = "DOWNLOAD_ATTACHMENT"

    # ── CALENDAR ──────────────────────────────────────────────────
    CREATE_EVENT = "CREATE_EVENT"
    LIST_EVENTS = "LIST_EVENTS"
    LIST_CALENDARS = "LIST_CALENDARS"
    UPDATE_EVENT = "UPDATE_EVENT"
    DELETE_EVENT = "DELETE_EVENT"
    SEARCH_EVENTS = "SEARCH_EVENTS"

    # ── REMINDERS ─────────────────────────────────────────────────
    CREATE_REMINDER = "CREATE_REMINDER"
    LIST_REMINDERS = "LIST_REMINDERS"
    LIST_REMINDER_LISTS = "LIST_REMINDER_LISTS"
    COMPLETE_REMINDER = "COMPLETE_REMINDER"
    UPDATE_REMINDER = "UPDATE_REMINDER"
    DELETE_REMINDER = "DELETE_REMINDER"

    # ── CONTACTS ──────────────────────────────────────────────────
    SEARCH_CONTACTS = "SEARCH_CONTACTS"
    GET_CONTACT = "GET_CONTACT"
    ADD_CONTACT = "ADD_CONTACT"
    UPDATE_CONTACT = "UPDATE_CONTACT"
    DELETE_CONTACT = "DELETE_CONTACT"

    # ── NOTES ─────────────────────────────────────────────────────
    CREATE_NOTE = "CREATE_NOTE"
    LIST_NOTES = "LIST_NOTES"

    # ── MESSAGES ──────────────────────────────────────────────────
    SEND_MESSAGE = "SEND_MESSAGE"

    # ── BROWSER ───────────────────────────────────────────────────
    OPEN_URL = "OPEN_URL"
    SEARCH_WEB = "SEARCH_WEB"
    GET_PAGE_CONTENT = "GET_PAGE_CONTENT"

    # ── CLIPBOARD ─────────────────────────────────────────────────
    GET_CLIPBOARD = "GET_CLIPBOARD"
    SET_CLIPBOARD = "SET_CLIPBOARD"

    # ── SEARCH ────────────────────────────────────────────────────
    SEARCH_SPOTLIGHT = "SEARCH_SPOTLIGHT"

    # ── NOTIFICATION ──────────────────────────────────────────────
    SHOW_NOTIFICATION = "SHOW_NOTIFICATION"

    # ── API ───────────────────────────────────────────────────────
    PAY_INVOICE = "PAY_INVOICE"
    HTTP_GET = "HTTP_GET"
    HTTP_POST = "HTTP_POST"

    # ── USER IO ───────────────────────────────────────────────────
    ASK_USER = "ASK_USER"
    SHOW_MESSAGE = "SHOW_MESSAGE"
    GET_CONFIRMATION = "GET_CONFIRMATION"

    # ── SYSTEM ────────────────────────────────────────────────────
    GET_SYSTEM_INFO = "GET_SYSTEM_INFO"
    SET_VOLUME = "SET_VOLUME"
    GET_VOLUME = "GET_VOLUME"
    TOGGLE_MUTE = "TOGGLE_MUTE"
    GET_MUTE = "GET_MUTE"
    SET_BRIGHTNESS = "SET_BRIGHTNESS"
    GET_BRIGHTNESS = "GET_BRIGHTNESS"
    TOGGLE_DARK_MODE = "TOGGLE_DARK_MODE"
    GET_DARK_MODE = "GET_DARK_MODE"

    # ── MESSAGES (extended) ───────────────────────────────────────
    READ_MESSAGES = "READ_MESSAGES"

    # ── NOTES (extended) ──────────────────────────────────────────
    READ_NOTE = "READ_NOTE"
    DELETE_NOTE = "DELETE_NOTE"


class ActionMeta(BaseModel):
    """Metadata for a registered action type.

    Stored in the ActionCatalog alongside each action type.
    Provides descriptive information — no rules or constraints.
    """

    model_config = ConfigDict(frozen=True)

    action_type: str
    category: ActionCategory
    description: str = ""
    platform: str = "universal"
    reversible: bool = False


# ── Category Mapping ─────────────────────────────────────────────────
# Which category each action type belongs to.
# This is the canonical source of truth for action→category mapping.

ACTION_CATEGORIES: dict[ActionType, ActionCategory] = {
    # FILE
    ActionType.LIST_DIRECTORY: ActionCategory.FILE,
    ActionType.READ_FILE: ActionCategory.FILE,
    ActionType.WRITE_FILE: ActionCategory.FILE,
    ActionType.APPEND_ROW: ActionCategory.FILE,
    ActionType.DELETE_FILE: ActionCategory.FILE,
    # HOST_FILE
    ActionType.READ_HOST_FILE: ActionCategory.HOST_FILE,
    ActionType.WRITE_HOST_FILE: ActionCategory.HOST_FILE,
    ActionType.DELETE_HOST_FILE: ActionCategory.HOST_FILE,
    ActionType.LIST_HOST_DIRECTORY: ActionCategory.HOST_FILE,
    # TERMINAL
    ActionType.RUN_COMMAND: ActionCategory.TERMINAL,
    # EMAIL
    ActionType.SEND_EMAIL: ActionCategory.EMAIL,
    ActionType.READ_EMAIL: ActionCategory.EMAIL,
    ActionType.SEARCH_EMAIL: ActionCategory.EMAIL,
    ActionType.GET_EMAIL: ActionCategory.EMAIL,
    ActionType.REPLY_EMAIL: ActionCategory.EMAIL,
    ActionType.FORWARD_EMAIL: ActionCategory.EMAIL,
    ActionType.MARK_READ_EMAIL: ActionCategory.EMAIL,
    ActionType.MOVE_EMAIL: ActionCategory.EMAIL,
    ActionType.DELETE_EMAIL: ActionCategory.EMAIL,
    ActionType.DOWNLOAD_ATTACHMENT: ActionCategory.EMAIL,
    # CALENDAR
    ActionType.CREATE_EVENT: ActionCategory.CALENDAR,
    ActionType.LIST_EVENTS: ActionCategory.CALENDAR,
    ActionType.LIST_CALENDARS: ActionCategory.CALENDAR,
    ActionType.UPDATE_EVENT: ActionCategory.CALENDAR,
    ActionType.DELETE_EVENT: ActionCategory.CALENDAR,
    ActionType.SEARCH_EVENTS: ActionCategory.CALENDAR,
    # REMINDERS
    ActionType.CREATE_REMINDER: ActionCategory.REMINDERS,
    ActionType.LIST_REMINDERS: ActionCategory.REMINDERS,
    ActionType.LIST_REMINDER_LISTS: ActionCategory.REMINDERS,
    ActionType.COMPLETE_REMINDER: ActionCategory.REMINDERS,
    ActionType.UPDATE_REMINDER: ActionCategory.REMINDERS,
    ActionType.DELETE_REMINDER: ActionCategory.REMINDERS,
    # CONTACTS
    ActionType.SEARCH_CONTACTS: ActionCategory.CONTACTS,
    ActionType.GET_CONTACT: ActionCategory.CONTACTS,
    ActionType.ADD_CONTACT: ActionCategory.CONTACTS,
    ActionType.UPDATE_CONTACT: ActionCategory.CONTACTS,
    ActionType.DELETE_CONTACT: ActionCategory.CONTACTS,
    # NOTES
    ActionType.CREATE_NOTE: ActionCategory.NOTES,
    ActionType.LIST_NOTES: ActionCategory.NOTES,
    # MESSAGES
    ActionType.SEND_MESSAGE: ActionCategory.MESSAGES,
    # BROWSER
    ActionType.OPEN_URL: ActionCategory.BROWSER,
    ActionType.SEARCH_WEB: ActionCategory.BROWSER,
    ActionType.GET_PAGE_CONTENT: ActionCategory.BROWSER,
    # CLIPBOARD
    ActionType.GET_CLIPBOARD: ActionCategory.CLIPBOARD,
    ActionType.SET_CLIPBOARD: ActionCategory.CLIPBOARD,
    # SEARCH
    ActionType.SEARCH_SPOTLIGHT: ActionCategory.SEARCH,
    # NOTIFICATION
    ActionType.SHOW_NOTIFICATION: ActionCategory.NOTIFICATION,
    # API
    ActionType.PAY_INVOICE: ActionCategory.API,
    ActionType.HTTP_GET: ActionCategory.API,
    ActionType.HTTP_POST: ActionCategory.API,
    # USER IO
    ActionType.ASK_USER: ActionCategory.USER_IO,
    ActionType.SHOW_MESSAGE: ActionCategory.USER_IO,
    ActionType.GET_CONFIRMATION: ActionCategory.USER_IO,
    # SYSTEM
    ActionType.GET_SYSTEM_INFO: ActionCategory.SYSTEM,
    ActionType.SET_VOLUME: ActionCategory.SYSTEM,
    ActionType.GET_VOLUME: ActionCategory.SYSTEM,
    ActionType.TOGGLE_MUTE: ActionCategory.SYSTEM,
    ActionType.GET_MUTE: ActionCategory.SYSTEM,
    ActionType.SET_BRIGHTNESS: ActionCategory.SYSTEM,
    ActionType.GET_BRIGHTNESS: ActionCategory.SYSTEM,
    ActionType.TOGGLE_DARK_MODE: ActionCategory.SYSTEM,
    ActionType.GET_DARK_MODE: ActionCategory.SYSTEM,
    # MESSAGES (extended)
    ActionType.READ_MESSAGES: ActionCategory.MESSAGES,
    # NOTES (extended)
    ActionType.READ_NOTE: ActionCategory.NOTES,
    ActionType.DELETE_NOTE: ActionCategory.NOTES,
}


class DomainType(str, Enum):
    """Critical domains that require typed intent data and structural enforcement.

    Actions in a critical domain must provide data conforming to the domain's
    schema (defined in intentframe_native_kit.action_registry.domains).  Guardian domain modules
    enforce structural constraints deterministically before AI evaluation.
    """

    FINANCE = "finance"
    DELETION = "deletion"


ACTION_DOMAINS: dict[ActionType, DomainType] = {
    ActionType.PAY_INVOICE: DomainType.FINANCE,
    ActionType.DELETE_FILE: DomainType.DELETION,
    ActionType.DELETE_HOST_FILE: DomainType.DELETION,
    # Path-oriented ``DeletionIntentData`` only — see ``domain_routes.py``.
    # ActionType.DELETE_EVENT: DomainType.DELETION,
    # ActionType.DELETE_REMINDER: DomainType.DELETION,
    # ActionType.DELETE_CONTACT: DomainType.DELETION,
    # ActionType.DELETE_NOTE: DomainType.DELETION,
}


def get_category(action_type: ActionType | str) -> ActionCategory:
    """Look up the category for an action type."""
    if isinstance(action_type, str):
        action_type = ActionType(action_type)
    return ACTION_CATEGORIES[action_type]


def get_domain(action_type: ActionType | str) -> DomainType | None:
    """Look up the critical domain for an action type, or None."""
    if isinstance(action_type, str):
        action_type = ActionType(action_type)
    return ACTION_DOMAINS.get(action_type)
