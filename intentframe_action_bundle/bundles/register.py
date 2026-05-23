"""Register all first-party action and domain bundles with the SDK."""

from __future__ import annotations

from intentframe_action_bundle.bundles.api import ApiActionBundle
from intentframe_action_bundle.bundles.browser import BrowserActionBundle
from intentframe_action_bundle.bundles.calendar import CalendarActionBundle
from intentframe_action_bundle.bundles.clipboard import ClipboardActionBundle
from intentframe_action_bundle.bundles.contacts import ContactsActionBundle
from intentframe_action_bundle.bundles.domain import DeletionDomainBundle, FinanceDomainBundle
from intentframe_action_bundle.bundles.email import EmailActionBundle
from intentframe_action_bundle.bundles.files import FilesActionBundle
from intentframe_action_bundle.bundles.host_files import HostFilesActionBundle
from intentframe_action_bundle.bundles.message import MessageActionBundle
from intentframe_action_bundle.bundles.notes import NotesActionBundle
from intentframe_action_bundle.bundles.reminders import RemindersActionBundle
from intentframe_action_bundle.bundles.spotlight import SpotlightActionBundle
from intentframe_action_bundle.bundles.system import SystemActionBundle
from intentframe_action_bundle.bundles.terminal import TerminalActionBundle
from intentframe_bundle_sdk.registry import register_action_bundle, register_domain_bundle

_BUNDLES_LOADED = False


def ensure_bundles_registered() -> None:
    global _BUNDLES_LOADED
    if _BUNDLES_LOADED:
        return

    register_action_bundle(TerminalActionBundle())
    register_action_bundle(FilesActionBundle())
    register_action_bundle(HostFilesActionBundle())
    register_action_bundle(EmailActionBundle())
    register_action_bundle(CalendarActionBundle())
    register_action_bundle(RemindersActionBundle())
    register_action_bundle(NotesActionBundle())
    register_action_bundle(ContactsActionBundle())
    register_action_bundle(MessageActionBundle())
    register_action_bundle(BrowserActionBundle())
    register_action_bundle(ApiActionBundle())
    register_action_bundle(ClipboardActionBundle())
    register_action_bundle(SpotlightActionBundle())
    register_action_bundle(SystemActionBundle())

    register_domain_bundle(FinanceDomainBundle())
    register_domain_bundle(DeletionDomainBundle())

    _BUNDLES_LOADED = True
