"""
macOS-specific action registrations.

Registers actions that are only available on macOS (Spotlight, Shortcuts,
macOS-native apps, etc.).  Maps 1:1 with executor adapters in
executor/platforms/macos/adapters/.

Universal actions (READ_FILE, SEND_EMAIL, etc.) are already registered
by catalog.register_defaults().  This module adds macOS-specific ones
and enriches universal actions with macOS-specific metadata.
"""

from __future__ import annotations

from action_registry.catalog import ActionCatalog
from action_registry.types import ActionCategory


def register_macos_actions(catalog: ActionCatalog) -> None:
    """Register macOS-specific actions and metadata.

    Call this after catalog.register_defaults().
    """

    # ── macOS-specific: Spotlight ─────────────────────────────────
    # SEARCH_SPOTLIGHT is already in the universal enum but is
    # macOS-only in practice.  Re-register with platform tag.
    catalog.register(
        "SEARCH_SPOTLIGHT",
        ActionCategory.SEARCH,
        description="Spotlight search (macOS)",
        platform="macos",
    )

    # ── macOS-specific: Shortcuts ─────────────────────────────────
    catalog.register(
        "RUN_SHORTCUT",
        ActionCategory.API,
        description="Run a macOS Shortcuts workflow",
        platform="macos",
    )

    # ── macOS-specific: Filesystem Watch ──────────────────────────
    catalog.register(
        "WATCH_FILESYSTEM",
        ActionCategory.FILE,
        description="Watch filesystem events (macOS FSEvents)",
        platform="macos",
    )

    # ── macOS-specific: System Control ────────────────────────────
    catalog.register(
        "GET_SYSTEM_INFO",
        ActionCategory.SYSTEM,
        description="Get macOS system information (OS version, hostname, architecture)",
        platform="macos",
    )
    catalog.register(
        "SET_VOLUME",
        ActionCategory.SYSTEM,
        description="Set system audio output volume (0–100)",
        platform="macos",
    )
    catalog.register(
        "SET_BRIGHTNESS",
        ActionCategory.SYSTEM,
        description="Set display brightness (0.0–1.0)",
        platform="macos",
    )
    catalog.register(
        "TOGGLE_DARK_MODE",
        ActionCategory.SYSTEM,
        description="Toggle macOS dark/light appearance",
        platform="macos",
    )

    # ── macOS-specific: Messages (extended) ───────────────────────
    catalog.register(
        "READ_MESSAGES",
        ActionCategory.MESSAGES,
        description="Read message history from Messages.app",
        platform="macos",
    )

    # ── macOS-specific: Notes (extended) ──────────────────────────
    catalog.register(
        "READ_NOTE",
        ActionCategory.NOTES,
        description="Read the body of a specific note by title",
        platform="macos",
    )
    catalog.register(
        "DELETE_NOTE",
        ActionCategory.NOTES,
        description="Delete a note by title",
        platform="macos",
    )
