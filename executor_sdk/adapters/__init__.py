"""
Capability adapter layer -- how the executor performs real-world actions.

Each adapter wraps a single OS or cloud capability (Mail, Calendar, Files,
etc.) behind the uniform CapabilityAdapter interface. The gateway doesn't
know or care what an adapter does internally -- it just calls safe_execute()
and gets back an ExecutionResult.

Platform-specific adapter implementations register themselves via
register_adapter() and are instantiated at startup from config.

Available adapters:
    Platform-neutral: console_user_io.py (console-based user I/O)

Implementations to create later (per platform):
    macOS: mail.py, calendar.py, contacts.py, files.py, notes.py,
           reminders.py, browser.py, messages.py, terminal.py,
           http_api.py, shortcuts.py, system.py, clipboard.py,
           notifications.py, spotlight.py, filesystem_watch.py, user_io.py
    Cloud: s3.py, ses.py, lambda_invoke.py, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from executor.adapters.base import CapabilityAdapter
from executor.adapters.console_user_io import ConsoleUserIOAdapter
from executor.exceptions import ConfigurationError

if TYPE_CHECKING:
    pass

__all__ = [
    "CapabilityAdapter",
    "ConsoleUserIOAdapter",
    "register_adapter",
    "create_adapter",
]

# ─── Plugin Registry ─────────────────────────────────────────────────────────

_ADAPTER_REGISTRY: dict[str, type[CapabilityAdapter]] = {}


def register_adapter(
    adapter_id: str, adapter_class: type[CapabilityAdapter]
) -> None:
    """Register an adapter implementation for config-driven instantiation.

    Platform-specific adapter modules call this at import time:
        register_adapter("mail", MailAdapter)
    """
    _ADAPTER_REGISTRY[adapter_id] = adapter_class


def create_adapter(adapter_id: str, **kwargs: Any) -> CapabilityAdapter:
    """Instantiate a registered adapter by ID.

    Args:
        adapter_id: The adapter identifier (e.g., "mail", "files").
        **kwargs: Dependencies injected into the adapter constructor
                  (e.g., credential_vault, virtual_filesystem).

    Returns:
        Configured CapabilityAdapter instance.

    Raises:
        ConfigurationError: If the adapter ID is not registered.
    """
    adapter_class = _ADAPTER_REGISTRY.get(adapter_id)
    if adapter_class is None:
        registered = ", ".join(sorted(_ADAPTER_REGISTRY)) or "(none)"
        raise ConfigurationError(
            f"Unknown adapter: '{adapter_id}'. "
            f"Registered adapters: {registered}",
        )
    return adapter_class(**kwargs)
