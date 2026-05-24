"""First-party action bundles — lazy public exports and registration."""

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
    from intentframe_action_bundle.api.bundle import ApiActionBundle
    from intentframe_action_bundle.browser.bundle import BrowserActionBundle
    from intentframe_action_bundle.calendar.bundle import CalendarActionBundle
    from intentframe_action_bundle.clipboard.bundle import ClipboardActionBundle
    from intentframe_action_bundle.contacts.bundle import ContactsActionBundle
    from intentframe_action_bundle.deletion.bundle import DeletionDomainBundle
    from intentframe_action_bundle.email.bundle import EmailActionBundle
    from intentframe_action_bundle.files.bundle import FilesActionBundle
    from intentframe_action_bundle.finance.bundle import (
        FinanceActionBundle,
        FinanceDomainBundle,
    )
    from intentframe_action_bundle.host_files.bundle import HostFilesActionBundle
    from intentframe_action_bundle.message.bundle import MessageActionBundle
    from intentframe_action_bundle.notes.bundle import NotesActionBundle
    from intentframe_action_bundle.reminders.bundle import RemindersActionBundle
    from intentframe_action_bundle.spotlight.bundle import SpotlightActionBundle
    from intentframe_action_bundle.system.bundle import SystemActionBundle
    from intentframe_action_bundle.terminal.bundle import TerminalActionBundle
    from intentframe_action_bundle.user_io.bundle import UserIoActionBundle

    for bundle in (
        TerminalActionBundle(),
        FilesActionBundle(),
        HostFilesActionBundle(),
        EmailActionBundle(),
        ApiActionBundle(),
        FinanceActionBundle(),
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
