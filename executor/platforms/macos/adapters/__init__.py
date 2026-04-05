"""
macOS capability adapters for IntentFrame Executor.

Each adapter wraps a macOS capability behind the uniform
CapabilityAdapter interface. Adapters are registered into the
executor's plugin registry so they can be instantiated from config.

TCC-gated and native-API adapters (calendar, reminders, contacts, notes,
messages, notifications, system brightness/dark mode) delegate to the
native platform server (macos-appkit-server) via HTTP-over-UDS.

Registration is fault-tolerant: if a specific adapter's dependencies
aren't installed (e.g., httpx), that adapter is skipped with a warning
rather than failing the entire platform registration.
"""

from __future__ import annotations

import importlib
import logging

from executor.adapters import register_adapter

logger = logging.getLogger(__name__)

# (adapter_id, module_name, class_name)
_ADAPTER_SPECS: list[tuple[str, str, str]] = [
    # Core adapters (stdlib / POSIX)
    ("files", "executor.platforms.macos.adapters.files", "FilesAdapter"),
    ("terminal", "executor.platforms.macos.adapters.terminal", "TerminalAdapter"),
    ("http_api", "executor.platforms.macos.adapters.http_api", "HttpApiAdapter"),
    ("user_io", "executor.platforms.macos.adapters.user_io", "UserIOAdapter"),
    ("notifications", "executor.platforms.macos.adapters.notifications", "NotificationsAdapter"),
    ("clipboard", "executor.platforms.macos.adapters.clipboard", "ClipboardAdapter"),
    ("shortcuts", "executor.platforms.macos.adapters.shortcuts", "ShortcutsAdapter"),
    ("spotlight", "executor.platforms.macos.adapters.spotlight", "SpotlightAdapter"),
    ("filesystem_watch", "executor.platforms.macos.adapters.filesystem_watch", "FilesystemWatchAdapter"),
    # PIM adapters — delegated to the native platform server (macos-appkit-server).
    # The Swift server owns TCC grants; these are thin httpx RPC clients.
    ("calendar", "executor.platforms.macos.adapters.calendar", "CalendarAdapter"),
    ("reminders", "executor.platforms.macos.adapters.reminders", "RemindersAdapter"),
    ("contacts", "executor.platforms.macos.adapters.contacts", "ContactsAdapter"),
    # Mail adapter — IMAP/SMTP protocols (stdlib imaplib / smtplib)
    # No GUI app launch: Mail.app is never opened.
    ("mail", "executor.platforms.macos.adapters.mail", "MailAdapter"),
    # Notes / Messages — delegated to the native platform server (macos-appkit-server).
    # The Swift server handles both reads (SQLite) and writes (NSAppleScript in-process).
    ("notes", "executor.platforms.macos.adapters.notes", "NotesAdapter"),
    ("messages", "executor.platforms.macos.adapters.messages", "MessagesAdapter"),
    # Browser adapter — default browser via subprocess `open` + httpx
    ("browser", "executor.platforms.macos.adapters.browser", "BrowserAdapter"),
    # System control — info & volume via stdlib/osascript; brightness & dark mode via platform server
    ("system", "executor.platforms.macos.adapters.system", "SystemAdapter"),
]


def register_all_adapters() -> None:
    """Register all macOS adapters that can be loaded.

    Adapters with missing dependencies are skipped with a warning.
    """
    registered = 0
    for adapter_id, module_path, class_name in _ADAPTER_SPECS:
        try:
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)
            register_adapter(adapter_id, adapter_class)
            registered += 1
        except ImportError as exc:
            logger.warning(
                "Skipping adapter '%s': missing dependency: %s", adapter_id, exc
            )
        except Exception as exc:
            logger.warning(
                "Skipping adapter '%s': load error: %s", adapter_id, exc
            )

    logger.info("Registered %d/%d macOS adapters", registered, len(_ADAPTER_SPECS))
