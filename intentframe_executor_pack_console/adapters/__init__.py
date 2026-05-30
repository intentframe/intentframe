"""Console capability adapters for IntentFrame Executor."""

from __future__ import annotations

from executor_sdk.adapters import register_adapter
from intentframe_executor_pack_console.adapters.console_user_io import ConsoleUserIOAdapter
from intentframe_executor_pack_console.adapters.simulated_user_io import SimulatedUserIOAdapter

__all__ = [
    "ConsoleUserIOAdapter",
    "SimulatedUserIOAdapter",
    "register_all_adapters",
]


def register_all_adapters() -> None:
    """Register console adapters."""
    register_adapter("console_user_io", ConsoleUserIOAdapter)
    register_adapter("simulated_user_io", SimulatedUserIOAdapter)
