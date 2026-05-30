"""Portable (POSIX) capability adapters for the IntentFrame Executor."""

from __future__ import annotations

from executor_sdk.adapters import register_adapter
from intentframe_executor_pack_posix.adapters.files import FilesAdapter

__all__ = ["FilesAdapter", "register_all_adapters"]


def register_all_adapters() -> None:
    """Register the portable adapters provided by the POSIX pack."""
    register_adapter("files", FilesAdapter)
