"""First-party native bundles — lazy public exports and registration."""

from __future__ import annotations

from intentframe_bundle_sdk.registry import (
    register_action_bundle,
    register_domain_bundle,
)

_BUNDLES_LOADED = False


def ensure_bundles_registered() -> None:
    """Load first-party bundles into the global SDK registry."""
    _ensure_first_party_bundles_loaded()


__all__ = [
    "register_bundles",
    "ensure_bundles_registered",
    "_ensure_first_party_bundles_loaded",
    "passive_read_action_ids",
]


def register_bundles(registry) -> None:
    """First-party register entry point."""
    from intentframe_native_bundles.actions.api.bundle import ApiActionBundle
    from intentframe_native_bundles.actions.browser.bundle import BrowserActionBundle
    from intentframe_native_bundles.actions.calendar.bundle import CalendarActionBundle
    from intentframe_native_bundles.actions.clipboard.bundle import ClipboardActionBundle
    from intentframe_native_bundles.actions.contacts.bundle import ContactsActionBundle
    from intentframe_native_bundles.actions.email.bundle import EmailActionBundle
    from intentframe_native_bundles.actions.files.bundle import FilesActionBundle
    from intentframe_native_bundles.actions.host_files.bundle import HostFilesActionBundle
    from intentframe_native_bundles.actions.message.bundle import MessageActionBundle
    from intentframe_native_bundles.actions.notes.bundle import NotesActionBundle
    from intentframe_native_bundles.actions.reminders.bundle import RemindersActionBundle
    from intentframe_native_bundles.actions.spotlight.bundle import SpotlightActionBundle
    from intentframe_native_bundles.actions.system.bundle import SystemActionBundle
    from intentframe_native_bundles.actions.terminal.bundle import TerminalActionBundle
    from intentframe_native_bundles.actions.user_io.bundle import UserIoActionBundle
    from intentframe_native_bundles.domains.deletion.bundle import DeletionDomainBundle
    from intentframe_native_bundles.domains.finance.bundle import FinanceDomainBundle

    for bundle in (
        TerminalActionBundle(),
        FilesActionBundle(),
        HostFilesActionBundle(),
        EmailActionBundle(),
        ApiActionBundle(),
        BrowserActionBundle(),
        MessageActionBundle(),
        CalendarActionBundle(),
        RemindersActionBundle(),
        NotesActionBundle(),
        ContactsActionBundle(),
        ClipboardActionBundle(),
        SpotlightActionBundle(),
        SystemActionBundle(),
        UserIoActionBundle(),
    ):
        registry.register_action_bundle(bundle)

    registry.register_domain_bundle(FinanceDomainBundle())
    registry.register_domain_bundle(DeletionDomainBundle())


def _ensure_first_party_bundles_loaded() -> None:
    global _BUNDLES_LOADED
    if _BUNDLES_LOADED:
        return
    register_bundles(
        type(
            "_RegistryShim",
            (),
            {
                "register_action_bundle": staticmethod(register_action_bundle),
                "register_domain_bundle": staticmethod(register_domain_bundle),
            },
        )()
    )
    _BUNDLES_LOADED = True


def passive_read_action_ids() -> frozenset[str]:
    """Registered passive-read action ids (SDK-owned fast path)."""
    from intentframe_bundle_sdk.registry import all_passive_read_action_ids

    _ensure_first_party_bundles_loaded()
    return all_passive_read_action_ids()
